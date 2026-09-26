"""core.parse_download 的纯离线回归检查。"""

from core.parse_download import ParseAPI, extract_media_items, extract_share_urls, sanitize_filename


def main():
    assert extract_share_urls("看这个 https://a.example/v/1。 再看 https://b.example/x),") == [
        "https://a.example/v/1", "https://b.example/x"
    ]
    assert sanitize_filename(' A/B:*? "demo". ') == 'A_B_ _demo_'

    wrapped = {
        "code": 200,
        "data": '{"title":"示例","author":{"nickname":"作者"},'
                '"video":{"nwm_video":"https://cdn.example/main.mp4"},'
                '"cover":"https://cdn.example/cover.jpg"}',
    }
    items = extract_media_items("https://share.example/1", wrapped)
    assert len(items) == 1
    assert items[0]["title"] == "示例"
    assert items[0]["author"] == "作者"
    assert items[0]["kind"] == "视频"
    assert items[0]["media_url"] == "https://cdn.example/main.mp4"

    assert not ParseAPI({}).is_configured()
    assert ParseAPI({
        "parse_api_url": "https://api.example/parse",
        "parse_api_uid": "company",
        "parse_api_key": "secret",
    }).is_configured()
    print("parse_download offline checks: PASS")


if __name__ == "__main__":
    main()
