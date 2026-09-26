"""Shared H.264 hardware encoder settings for Kuai AI worker modes."""

GPU_OPTIONS = {
    "nvidia": (
        "-preset", "p5", "-rc", "vbr", "-cq", "21",
        "-spatial-aq", "1", "-temporal-aq", "1",
    ),
    "amd": (
        "-quality", "balanced", "-rc", "cqp", "-qp_i", "21", "-qp_p", "23",
    ),
}


def select_h264_encoder(state, use_gpu):
    if not use_gpu:
        return "libx264", (), ""

    profile = (state or {}).get("gpu_profile") or {}
    if not profile.get("available"):
        return "", (), "未检测到可用的GPU硬件编码器"

    vendor = profile.get("vendor")
    encoder = profile.get("h264_encoder")
    options = GPU_OPTIONS.get(vendor)
    if not encoder or options is None:
        return "", (), "当前GPU没有可用的H.264硬件编码配置"
    return str(encoder), options, ""