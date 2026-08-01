# cython: language_level=3
"""FlowCut native security and processing core."""

import base64
import hashlib
import hmac
import json
import time

from cryptography.hazmat.primitives import serialization

APP_ID = "blackcat-flowcut"
SERVER_PUBLIC_KEY = b"""-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEAh2j/V2PHHxUJ+IUjr25ecNb7PDn538SopwI6qWg512s=
-----END PUBLIC KEY-----"""


cdef extern from "VMProtectSDK.h":
    void VMProtectBeginUltra(const char *name)
    void VMProtectEnd()


cdef bytes _b64url_decode(str value):
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


cdef dict _verify_task(
    str token,
    str engine,
    str batch_id,
    int input_count,
    str params_hash,
    str device_code,
    str device_fingerprint,
):
    parts = token.split(".")
    if len(parts) != 2:
        raise ValueError("任务令牌格式无效")
    payload_text = _b64url_decode(parts[0]).decode("utf-8")
    signature_text = _b64url_decode(parts[1]).decode("ascii")
    key = serialization.load_pem_public_key(SERVER_PUBLIC_KEY)
    key.verify(base64.b64decode(signature_text), payload_text.encode("utf-8"))
    claims = json.loads(payload_text)
    expected = {
        "tokenType": "blackcat-task",
        "appId": APP_ID,
        "engine": engine,
        "batchId": batch_id,
        "inputCount": input_count,
        "paramsHash": params_hash,
        "deviceCode": device_code,
        "deviceFingerprint": device_fingerprint,
    }
    for name, value in expected.items():
        if claims.get(name) != value:
            raise ValueError(f"任务令牌字段不匹配: {name}")
    if int(claims.get("expiresAt", 0)) <= int(time.time() * 1000):
        raise ValueError("任务令牌已过期")
    return claims


cdef str _mask_alpha(int width, int height, int feather, double margin_tb, double margin_lr):
    edge = max(1, round(feather * min(width, height) / 1080))
    fades = []
    if margin_lr > 0:
        fades.extend((
            f"clip((X-W*{margin_lr}+{edge / 2})/{edge},0,1)",
            f"clip((W*(1-{margin_lr})-X+{edge / 2})/{edge},0,1)",
        ))
    if margin_tb > 0:
        fades.extend((
            f"clip((Y-H*{margin_tb}+{edge / 2})/{edge},0,1)",
            f"clip((H*(1-{margin_tb})-Y+{edge / 2})/{edge},0,1)",
        ))
    if not fades:
        return ""
    expression = fades[0]
    for fade in fades[1:]:
        expression = f"min({expression},{fade})"
    return f"255*{expression}"


cdef dict _butterfly_plan(double duration, double head, object hidden, int fps):
    hidden_value = duration + 0.0667 if hidden is None else float(hidden)
    chunks = [23.0] * int(hidden_value // 23)
    if hidden_value - sum(chunks) > 0.02:
        chunks.append(hidden_value - sum(chunks))
    return {
        "hidden": hidden_value,
        "chunks": chunks,
        "jump_frame": round((head + hidden_value) * fps),
        "main_frames": round(duration * fps),
    }


cpdef str sign_request(str secret, str stable_json):
    VMProtectBeginUltra(b"FCNATIVE:license.sign")
    result = base64.urlsafe_b64encode(
        hmac.new(
            secret.encode("utf-8"),
            stable_json.encode("utf-8"),
            hashlib.sha256,
        ).digest()
    ).decode("ascii").rstrip("=")
    VMProtectEnd()
    return result


cpdef verify_response(bytes public_key_pem, str stable_json, str signature):
    VMProtectBeginUltra(b"FCNATIVE:license.verify")
    key = serialization.load_pem_public_key(public_key_pem)
    key.verify(base64.b64decode(signature), stable_json.encode("utf-8"))
    VMProtectEnd()
    return True


cpdef str mask_alpha(int width, int height, int feather, double margin_tb, double margin_lr):
    VMProtectBeginUltra(b"FCNATIVE:mask.alpha")
    result = _mask_alpha(width, height, feather, margin_tb, margin_lr)
    VMProtectEnd()
    return result


cpdef dict task_claims(
    str token, str engine, str batch_id,
    int input_count, str params_hash, str device_code, str device_fingerprint,
):
    VMProtectBeginUltra(b"FCNATIVE:task.verify")
    result = _verify_task(
        token, engine, batch_id, input_count,
        params_hash, device_code, device_fingerprint,
    )
    VMProtectEnd()
    return result


cpdef str authorized_mask_alpha(
    str token, str engine, str batch_id,
    int input_count, str params_hash, str device_code, str device_fingerprint,
    int width, int height, int feather, double margin_tb, double margin_lr,
):
    VMProtectBeginUltra(b"FCNATIVE:mask.authorized")
    _verify_task(
        token, engine, batch_id, input_count,
        params_hash, device_code, device_fingerprint,
    )
    result = _mask_alpha(width, height, feather, margin_tb, margin_lr)
    VMProtectEnd()
    return result


cpdef dict authorized_butterfly_plan(
    str token, str engine, str batch_id,
    int input_count, str params_hash, str device_code, str device_fingerprint,
    double duration, double head, object hidden, int fps=30,
):
    VMProtectBeginUltra(b"FCNATIVE:butterfly.authorized")
    _verify_task(
        token, engine, batch_id, input_count,
        params_hash, device_code, device_fingerprint,
    )
    result = _butterfly_plan(duration, head, hidden, fps)
    VMProtectEnd()
    return result
