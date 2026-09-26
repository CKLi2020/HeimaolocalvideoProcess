"""Shared HEVC hardware encoder settings for Douyin worker modes."""

GPU_OPTIONS = {
    "nvidia": (
        "-preset", "p5", "-rc", "vbr", "-cq", "21",
        "-spatial-aq", "1", "-temporal-aq", "1",
    ),
    "amd": (
        "-quality", "balanced", "-rc", "cqp", "-qp_i", "21", "-qp_p", "23",
    ),
}


def select_hevc_encoder(state, use_gpu):
    if not use_gpu:
        return "libx265", (), ""

    profile = (state or {}).get("gpu_profile") or {}
    if not profile.get("available"):
        return "", (), "未检测到可用的GPU硬件编码器"

    vendor = profile.get("vendor")
    encoder = profile.get("hevc_encoder")
    options = GPU_OPTIONS.get(vendor)
    if not encoder or options is None:
        return "", (), "当前GPU没有可用的HEVC硬件编码配置"
    return str(encoder), options, ""