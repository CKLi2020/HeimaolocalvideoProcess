from app.main_window import _format_expire_at


def test_format_expire_at():
    assert _format_expire_at("") == "永久"
    assert _format_expire_at("2026-08-04T15:59:00Z").startswith("2026-08-04 ")
