"""PyAV 进程内合成引擎。

使用 av (PyAV) 库进行进程内逐帧合成，无需启动外部 ffmpeg 进程。
支持多线程并行合成，比 ffmpeg CLI 模式更快。

依赖: av (PyAV), numpy
"""

from __future__ import annotations

import concurrent.futures
from pathlib import Path
from typing import Callable, List, Optional

import av
import numpy as np


def compose_single(
    main_video: Path,
    background_video: Path,
    output_path: Path,
    width: int = 1080,
    height: int = 1920,
    fps: int = 30,
    main_scale: float = 1.05,
    crf: int = 23,
    preset: str = "medium",
    log_callback: Optional[Callable[[str], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> bool:
    """PyAV 进程内合成单个视频。

    比 ffmpeg CLI 更高效：无进程启动开销，直接操作帧数据。

    Args:
        main_video: 主视频路径
        background_video: 背景视频路径
        output_path: 输出路径
        width, height: 输出画布尺寸
        fps: 输出帧率
        main_scale: 主视频缩放比例
        crf: 编码质量
        preset: 编码速度预设
        log_callback: 日志回调
        cancel_check: 取消检查

    Returns:
        成功返回 True
    """
    log = log_callback or (lambda _: None)

    try:
        # 打开输入
        bg_container = av.open(str(background_video))
        main_container = av.open(str(main_video))

        bg_stream = bg_container.streams.video[0]
        main_stream = main_container.streams.video[0]

        # 输出
        out_container = av.open(str(output_path), "w")
        out_stream = out_container.add_stream("libx264", rate=fps)
        out_stream.width = width
        out_stream.height = height
        out_stream.pix_fmt = "yuv420p"
        out_stream.options = {"crf": str(crf), "preset": preset}

        # 复制音频流（如果有）
        audio_streams = [s for s in main_container.streams if s.type == "audio"]
        out_audio = None
        if audio_streams:
            out_audio = out_container.add_stream("aac", rate=48000)
            out_audio.channels = 2
            out_audio.layout = "stereo"

        frame_count = 0
        bg_frame_iter = iter(bg_container.decode(video=0))
        main_frame_iter = iter(main_container.decode(video=0))
        audio_packets_iter = iter(main_container.demux(audio_streams[0])) if audio_streams else None

        # 预解码背景帧到列表（循环用）
        bg_frames: List[av.VideoFrame] = []
        for frame in bg_frame_iter:
            bg_frames.append(frame)
            if len(bg_frames) > 300:  # 限制缓存
                break

        if not bg_frames:
            log("[PyAV] 背景视频无帧")
            return False

        main_frames: List[av.VideoFrame] = []
        for frame in main_frame_iter:
            main_frames.append(frame)
        if not main_frames:
            log("[PyAV] 主视频无帧")
            return False

        log(f"[PyAV] 合成: {len(main_frames)} 主帧, {len(bg_frames)} 背景帧")

        bg_idx = 0
        for i, main_frame in enumerate(main_frames):
            if cancel_check and cancel_check():
                log("[PyAV] 用户停止")
                return False

            # 背景帧循环
            bg_frame = bg_frames[bg_idx % len(bg_frames)]
            bg_idx += 1

            # 转换到 numpy 数组
            bg_img = bg_frame.to_ndarray(format="rgb24")
            main_img = main_frame.to_ndarray(format="rgb24")

            # 缩放背景到画布
            bg_h, bg_w = bg_img.shape[:2]
            bg_scaled = _resize_crop(bg_img, width, height)

            # 缩放任主视频
            mh, mw = main_img.shape[:2]
            new_mw = int(mw * main_scale)
            new_mh = int(mh * main_scale)
            main_scaled = _resize(main_img, new_mw, new_mh)

            # 居中叠加
            ox = (width - new_mw) // 2
            oy = (height - new_mh) // 2
            result = bg_scaled.copy()
            _overlay_center(result, main_scaled, ox, oy)

            # 编码输出帧
            out_frame = av.VideoFrame.from_ndarray(result, format="rgb24")
            out_frame = out_frame.reformat(format="yuv420p")
            for packet in out_stream.encode(out_frame):
                out_container.mux(packet)

            if i % 30 == 0:
                log(f"[PyAV] 进度: {i+1}/{len(main_frames)}")

        # Flush 编码器
        for packet in out_stream.encode():
            out_container.mux(packet)

        # 复制音频
        if out_audio and audio_packets_iter:
            for packet in audio_packets_iter:
                if packet.stream.type == "audio":
                    packet.stream = out_audio
                    out_container.mux(packet)

        out_container.close()
        bg_container.close()
        main_container.close()

        log(f"[PyAV] 合成完成: {output_path.name}")
        return True

    except ImportError:
        log("[PyAV] av 库不可用，请使用 ffmpeg CLI 模式")
        return False
    except Exception as e:
        log(f"[PyAV] 合成失败: {e}")
        return False


def compose_batch_parallel(
    jobs: List[dict],
    threads: int = 4,
    log_callback: Optional[Callable[[str], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> int:
    """多线程并行合成多个视频。

    Args:
        jobs: [{main_video, background_video, output_path, ...}, ...]
        threads: 并行线程数
        log_callback: 日志回调
        cancel_check: 取消检查

    Returns:
        成功完成的任务数
    """
    log = log_callback or (lambda _: None)
    success = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=threads) as executor:
        futures = {
            executor.submit(compose_single, **job, log_callback=log, cancel_check=cancel_check): job
            for job in jobs
        }
        for future in concurrent.futures.as_completed(futures):
            if future.result():
                success += 1

    log(f"[PyAV] 并行完成: {success}/{len(jobs)}")
    return success


# ── 图像处理辅助 ──

def _resize(img: np.ndarray, w: int, h: int) -> np.ndarray:
    """简单最近邻缩放 (无 PIL 依赖)。"""
    import cv2
    return cv2.resize(img, (w, h), interpolation=cv2.INTER_LANCZOS4)


def _resize_crop(img: np.ndarray, tw: int, th: int) -> np.ndarray:
    """缩放并居中裁切到目标尺寸。"""
    import cv2
    h, w = img.shape[:2]
    scale = max(tw / w, th / h)
    nw, nh = int(w * scale), int(h * scale)
    resized = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LANCZOS4)
    ox = (nw - tw) // 2
    oy = (nh - th) // 2
    return resized[oy:oy + th, ox:ox + tw]


def _overlay_center(bg: np.ndarray, fg: np.ndarray, ox: int, oy: int) -> None:
    """将前景居中叠加到背景上（原地修改）。"""
    fh, fw = fg.shape[:2]
    bh, bw = bg.shape[:2]

    x1 = max(0, ox)
    y1 = max(0, oy)
    x2 = min(bw, ox + fw)
    y2 = min(bh, oy + fh)

    fx1 = max(0, -ox)
    fy1 = max(0, -oy)
    fx2 = fx1 + (x2 - x1)
    fy2 = fy1 + (y2 - y1)

    if x2 > x1 and y2 > y1:
        bg[y1:y2, x1:x2] = fg[fy1:fy2, fx1:fx2]
