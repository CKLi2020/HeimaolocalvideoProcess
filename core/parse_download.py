"""第三方短视频解析与下载工具。

本模块按原二进制中保留的函数名、参数名、常量和错误文案重建。
解析接口属于第三方服务；这里恢复客户端协议与本地数据处理，不包含账号或密钥。
"""

import json
import mimetypes
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request


URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif")
_VIDEO_EXTS = (".mp4", ".mov", ".m3u8", ".flv", ".mkv")


def extract_share_urls(text):
    """从多行分享文案中提取链接，一行多个也能识别。"""
    urls, seen = [], set()
    for url in URL_RE.findall(str(text or "")):
        url = url.rstrip("，。；,;)")
        if url and url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def sanitize_filename(name, fallback="media"):
    text = re.sub(r'[\\/:*?"<>|\r\n]+', "_", str(name or "").strip())
    text = re.sub(r"\s+", " ", text).strip(" .")
    return text or fallback


def _decode_jsonish(value, depth=0):
    """Some parser APIs wrap JSON inside string fields."""
    if depth > 5:
        return value
    if isinstance(value, str):
        text = value.strip()
        if ((text.startswith("{") and text.endswith("}")) or
                (text.startswith("[") and text.endswith("]"))):
            try:
                return _decode_jsonish(json.loads(text), depth + 1)
            except json.JSONDecodeError:
                return value
        return value
    if isinstance(value, dict):
        return {key: _decode_jsonish(item, depth + 1) for key, item in value.items()}
    if isinstance(value, list):
        return [_decode_jsonish(item, depth + 1) for item in value]
    return value


def _short_text(value, limit=180):
    text = str(value or "").strip()
    return text if len(text) <= limit else text[:limit] + "..."


def _first_text(obj, keys):
    wanted = {str(key).lower() for key in keys}
    if isinstance(obj, dict):
        for key, value in obj.items():
            if (str(key).lower() in wanted and value not in (None, "", [], {})
                    and not isinstance(value, (dict, list))):
                return str(value)
        for value in obj.values():
            hit = _first_text(value, wanted)
            if hit:
                return hit
    elif isinstance(obj, list):
        for value in obj:
            hit = _first_text(value, wanted)
            if hit:
                return hit
    return ""


def _guess_kind(url, key=""):
    text = (str(url or "") + " " + str(key or "")).lower()
    path = urllib.parse.urlsplit(str(url or "")).path.lower()
    if path.endswith(_IMAGE_EXTS) or any(word in text for word in
                                         ("image", "images", "pic", "cover", "图片")):
        return "图片"
    if path.endswith(_VIDEO_EXTS) or any(word in text for word in
                                         ("video", "play", "wm_video", "视频", "媒体")):
        return "视频"
    return "媒体"


def _walk_media(obj, found=None, path=()):
    found = found if found is not None else []
    if isinstance(obj, dict):
        for key, value in obj.items():
            next_path = path + (str(key),)
            if isinstance(value, str) and value.lower().startswith(("http://", "https://")):
                found.append({
                    "url": value,
                    "kind": _guess_kind(value, key),
                    "path": "/".join(next_path),
                })
            else:
                _walk_media(value, found, next_path)
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            _walk_media(value, found, path + (str(index),))
    return found


def _select_download_media(raw_media):
    cleaned, seen = [], set()
    for item in raw_media:
        url = str(item.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        copy = dict(item)
        copy["url"] = url
        cleaned.append(copy)

    excluded = ("avatar", "icon", "logo", "music")
    useful = [item for item in cleaned
              if not any(word in item.get("path", "").lower() for word in excluded)]
    videos = [item for item in useful if item.get("kind") == "视频"]
    primary = [item for item in videos if any(word in item.get("path", "").lower()
                                               for word in ("origin", "nwm", "nowater", "download"))]
    pictures = [item for item in useful if item.get("kind") == "图片"]

    if primary:
        return primary[:1]
    if videos:
        return videos[:1]
    return pictures


def extract_media_items(source_url, response):
    """兼容常见短视频解析 API 返回结构，尽量提取可下载媒体。"""
    data = _decode_jsonish(response)
    title = _first_text(data, ("title", "desc", "description", "name", "text")) or "解析视频"
    author = _first_text(data, ("author", "nickname", "user", "username", "owner"))
    duration = _first_text(data, ("duration", "time", "video_duration"))
    selected = _select_download_media(_walk_media(data))

    items = []
    for index, media in enumerate(selected, 1):
        item_title = title if len(selected) == 1 else "%s_%03d" % (title, index)
        items.append({
            "title": item_title,
            "author": author,
            "duration": duration,
            "kind": media.get("kind") or "媒体",
            "media_url": media["url"],
            "source_url": source_url,
            "status": "已解析",
            "progress": "0%",
        })
    return items


class ParseAPI:
    def __init__(self, cfg):
        cfg = cfg or {}
        self.endpoint = str(cfg.get("parse_api_url") or
                            "https://syapi.chuangye.site/home/api").strip()
        self.product_type = str(cfg.get("parse_api_type") or "dsp").strip()
        self.uid = str(cfg.get("parse_api_uid") or "uid").strip()
        self.key = str(cfg.get("parse_api_key") or "key").strip()

    def is_configured(self):
        values = (self.endpoint, self.uid, self.key)
        return (all(values) and self.uid.lower() != "uid" and self.key.lower() != "key"
                and not any(value.upper().startswith("YOUR_") for value in values))

    def parse(self, share_url):
        if not self.is_configured():
            raise RuntimeError("请先在 client/config.json 填写 parse_api_uid 和 parse_api_key")

        params = {
            "url": str(share_url or "").strip(),
            "type": self.product_type,
            "uid": self.uid,
            "key": self.key,
        }
        separator = "&" if "?" in self.endpoint else "?"
        url = self.endpoint + separator + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json,text/plain,*/*",
        })
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace") if exc.fp else ""
            raise RuntimeError("解析接口 HTTP %s: %s" % (exc.code, _short_text(body))) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError("解析接口连接失败: %s" % exc.reason) from exc

        raw_text = raw.decode("utf-8-sig", "replace")
        try:
            data = _decode_jsonish(json.loads(raw_text))
        except json.JSONDecodeError as exc:
            raise RuntimeError("解析接口返回不是 JSON: %s" % _short_text(raw_text)) from exc
        if not isinstance(data, dict):
            raise RuntimeError("解析接口返回格式异常")

        ok_value = data.get("code", data.get("status", data.get("success")))
        success_codes = {None, True, 0, 1, 200, "0", "1", "200", "success", "ok", "成功"}
        if ok_value not in success_codes:
            msg_text = data.get("msg") or data.get("message") or data.get("error") or "解析失败"
            raise RuntimeError(str(msg_text))
        return data.get("data", data)


def _filename_ext_from_response(url, headers, kind):
    content_type = str(headers.get("Content-Type", "")).split(";", 1)[0].strip()
    ext = mimetypes.guess_extension(content_type) or ""
    if ext == ".jpe":
        ext = ".jpg"
    url_ext = os.path.splitext(urllib.parse.urlsplit(url).path)[1].lower()
    if url_ext in _IMAGE_EXTS + _VIDEO_EXTS:
        ext = url_ext
    return ext or (".mp4" if kind == "视频" else ".jpg")


def download_media(item, output_dir, index=1, stop_event=None, progress=None):
    os.makedirs(output_dir, exist_ok=True)
    headers = {"User-Agent": "Mozilla/5.0"}
    if item.get("source_url"):
        headers["Referer"] = item["source_url"]
    req = urllib.request.Request(item["media_url"], headers=headers)

    with urllib.request.urlopen(req, timeout=60) as resp:
        try:
            total = int(resp.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            total = 0
        ext = _filename_ext_from_response(item["media_url"], resp.headers,
                                          item.get("kind") or "媒体")
        base = sanitize_filename(item.get("title"), "media_%03d" % index)
        path = os.path.join(output_dir, base + ext)
        done, last_emit = 0, 0.0
        with open(path, "wb") as fh:
            while True:
                if stop_event is not None and stop_event.is_set():
                    raise RuntimeError("已停止")
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                fh.write(chunk)
                done += len(chunk)
                now = time.time()
                if progress and now - last_emit >= 0.15:
                    progress(min(99, int(done * 100 / total)) if total else 0)
                    last_emit = now
        if progress:
            progress(100)
        return path


__all__ = [
    "ParseAPI", "download_media", "extract_media_items", "extract_share_urls",
    "sanitize_filename",
]
