# -*- coding: utf-8 -*-
"""安全层：本机令牌、Host 防 DNS-rebind、密钥加密保管（Fernet）、审计。"""
from __future__ import annotations
import hmac
import secrets
from typing import Optional

from fastapi import Request
from fastapi.responses import JSONResponse

from .config import TOKEN_PATH, KEY_PATH, load_config
from .db import audit

ALLOWED_HOSTS = {"127.0.0.1:8765", "localhost:8765", "127.0.0.1", "localhost"}

# ---------- 访问令牌（仅本机引导时可读） ----------
def get_or_create_token() -> str:
    # Tauri sidecar 场景：由外壳进程生成并经环境变量注入，保证 webview 与后端一致
    env_token = __import__("os").environ.get("LW_AUTO_TOKEN", "").strip()
    if env_token:
        return env_token
    if TOKEN_PATH.exists():
        t = TOKEN_PATH.read_text(encoding="utf-8").strip()
        if t:
            return t
    t = secrets.token_urlsafe(32)
    TOKEN_PATH.write_text(t, encoding="utf-8")
    try:
        import os
        os.chmod(TOKEN_PATH, 0o600)
    except OSError:
        pass
    return t


def host_allowed(request: Request) -> bool:
    host = (request.headers.get("host") or "").split(",")[0].strip().lower()
    cfg = load_config()
    port = cfg.get("port", 8765)
    ok = host in ALLOWED_HOSTS or host in {f"127.0.0.1:{port}", f"localhost:{port}"}
    if not ok:
        audit("安全拦截", f"非法Host: {host} ip={request.client.host if request.client else '?'}")
    return ok


def token_valid(request: Request) -> bool:
    expected = get_or_create_token()
    got = request.headers.get("x-auth-token") or ""
    if not got:
        auth = request.headers.get("authorization") or ""
        if auth.lower().startswith("bearer "):
            got = auth[7:]
    if request.query_params.get("token"):
        got = request.query_params["token"]
    return hmac.compare_digest(got, expected)


async def security_middleware(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api/") and path != "/api/bootstrap":
        if not host_allowed(request):
            return JSONResponse({"ok": False, "error": "非法 Host，拒绝访问"}, status_code=403)
        if not token_valid(request):
            audit("安全拦截", f"缺少/错误令牌 path={path}")
            return JSONResponse({"ok": False, "error": "未授权"}, status_code=401)
    return await call_next(request)


# ---------- 敏感凭据加密保管（飞书/微信 secret） ----------
class SecretStore:
    def __init__(self):
        self._fernet = None
        self.reason = ""
        try:
            from cryptography.fernet import Fernet
            if KEY_PATH.exists():
                key = KEY_PATH.read_bytes()
            else:
                key = Fernet.generate_key()
                KEY_PATH.write_bytes(key)
            self._fernet = Fernet(key)
        except Exception as e:  # 未安装 cryptography 时不允许明文保存密钥
            self.reason = f"加密组件不可用: {e}"

    @property
    def available(self) -> bool:
        return self._fernet is not None

    def encrypt(self, plain: str) -> str:
        if not plain:
            return ""
        if not self._fernet:
            raise RuntimeError("加密组件不可用，拒绝明文保存凭据")
        return self._fernet.encrypt(plain.encode("utf-8")).decode("ascii")

    def decrypt(self, token: str) -> str:
        if not token or not self._fernet:
            return ""
        try:
            return self._fernet.decrypt(token.encode("ascii")).decode("utf-8")
        except Exception:
            return ""


SECRETS = SecretStore()
