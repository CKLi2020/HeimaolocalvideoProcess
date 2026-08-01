"""FlowCut 卡密授权：HMAC 请求、Ed25519 响应验签和设备绑定。"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import platform
import ssl
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from urllib.parse import urlparse

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from app._flowcut_core import sign_request, verify_response


APP_ID = "blackcat-flowcut"
APP_VERSION = "1.0.0"
DEFAULT_API_BASE = "https://yizhixiangsi.cn"
REQUEST_SECRET = "fc-client-request-v1-8c7f67c5e4fa49c3888e21135d72976a"
SERVER_PUBLIC_KEY = b"""-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEAh2j/V2PHHxUJ+IUjr25ecNb7PDn538SopwI6qWg512s=
-----END PUBLIC KEY-----"""


class LicenseError(RuntimeError):
    pass


def _config_path() -> Path:
    folder = Path(os.getenv("APPDATA", Path.home())) / "BlackCatFlowCut"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "license.json"


def _stable_json(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sign(payload: dict) -> str:
    return sign_request(REQUEST_SECRET, _stable_json(payload))


def _fingerprint() -> str:
    if os.name == "nt":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Cryptography",
            ) as key:
                raw = str(winreg.QueryValueEx(key, "MachineGuid")[0])
        except OSError:
            raw = f"{uuid.getnode()}|{platform.node()}|{os.getenv('COMPUTERNAME', '')}"
    else:
        raw = f"{uuid.getnode()}|{platform.node()}|{platform.system()}|{platform.machine()}"
    return hashlib.sha256(raw.encode("utf-8", "ignore")).hexdigest()


def _require_secure_url(api_base: str) -> None:
    url = urlparse(api_base)
    if url.scheme == "https":
        return
    if url.scheme == "http" and url.hostname in {"localhost", "127.0.0.1"}:
        return
    raise LicenseError("授权服务器必须使用 HTTPS")


class LicenseClient:
    def __init__(self) -> None:
        self.session_id = uuid.uuid4().hex
        self.fingerprint = _fingerprint()
        self.device_code = self.fingerprint[:32]
        try:
            self.config = json.loads(_config_path().read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self.config = {}

    @property
    def api_base(self) -> str:
        return (
            os.getenv("BLACKCAT_LICENSE_API_BASE")
            or self.config.get("apiBase")
            or DEFAULT_API_BASE
        )

    @property
    def license_code(self) -> str:
        return self.config.get("licenseCode", "")

    def has_license(self) -> bool:
        return bool(self.license_code)

    def activate(self, api_base: str, license_code: str) -> dict:
        previous = self.config
        self.config = {
            "apiBase": api_base.rstrip("/"),
            "licenseCode": license_code.strip().upper(),
        }
        try:
            data = self._request("activate")
        except Exception:
            self.config = previous
            raise
        _config_path().write_text(
            json.dumps(self.config, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return data

    def check(self) -> dict:
        return self._request("check")

    def task_token(
        self,
        engine: str,
        batch_id: str,
        input_count: int,
        params_hash: str,
    ) -> str:
        data = self._request(
            "task-token",
            {
                "engine": engine,
                "batchId": batch_id,
                "inputCount": input_count,
                "paramsHash": params_hash,
            },
        )
        token = data.get("taskToken") or ""
        if not token:
            raise LicenseError("服务器未返回任务令牌")
        return token

    def _request(self, action: str, extra: dict | None = None) -> dict:
        if not self.license_code:
            raise LicenseError("请输入卡密")
        _require_secure_url(self.api_base)
        payload = {
            "licenseCode": self.license_code,
            "deviceCode": self.device_code,
            "deviceFingerprint": self.fingerprint,
            "timestamp": int(time.time() * 1000),
            "nonce": uuid.uuid4().hex,
            "requestId": uuid.uuid4().hex,
            "sessionId": self.session_id,
            "appId": APP_ID,
            "appVersion": APP_VERSION,
        }
        if extra:
            payload.update(extra)
        payload["requestSignature"] = _sign(payload)
        request = urllib.request.Request(
            f"{self.api_base.rstrip('/')}/api/license/{action}",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({}),
                urllib.request.HTTPSHandler(context=ssl.create_default_context()),
            )
            with opener.open(request, timeout=12) as response:
                body = json.loads(response.read().decode())
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as error:
            raise LicenseError(f"授权服务器连接失败：{error}") from error

        data = body.get("data") or {}
        try:
            verify_response(
                SERVER_PUBLIC_KEY,
                _stable_json(data),
                body.get("signature") or "",
            )
        except Exception as error:
            raise LicenseError("授权服务器响应签名无效") from error
        if not hmac.compare_digest(body.get("responseHmac") or "", _sign(data)):
            raise LicenseError("授权服务器响应校验失败")
        if not data.get("canUse"):
            raise LicenseError(data.get("message") or data.get("reason") or "授权失败")
        return data


class LicenseDialog(QDialog):
    def __init__(self, client: LicenseClient):
        super().__init__()
        self.client = client
        self.setWindowTitle("黑猫苍老师 - 卡密授权")
        self.setModal(True)
        self.setFixedSize(460, 190)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("请输入服务器后台生成的黑猫苍老师卡密"))
        self.api = QLineEdit(client.api_base)
        self.api.hide()
        row = QHBoxLayout()
        row.addWidget(QLabel("卡密"))
        self.code = QLineEdit(client.license_code)
        self.code.setPlaceholderText("请输入卡密")
        row.addWidget(self.code)
        layout.addLayout(row)
        buttons = QHBoxLayout()
        login = QPushButton("登录")
        login.setObjectName("accent")
        login.clicked.connect(self._activate)
        buttons.addWidget(login)
        cancel = QPushButton("退出")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)

    def _activate(self) -> None:
        try:
            self.client.activate(self.api.text().strip(), self.code.text().strip())
        except LicenseError as error:
            QMessageBox.warning(self, "授权失败", str(error))
            return
        self.accept()
