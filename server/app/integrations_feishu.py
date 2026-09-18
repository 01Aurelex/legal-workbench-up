# -*- coding: utf-8 -*-
"""飞书开放平台适配器（预留接口，需求5）。
凭据经 Fernet 加密后只存本地；未配置时只返回状态，不发起任何网络请求。
一键同步路径：先 upload_all 上传到云空间，再用 import_tasks 转为飞书云文档。"""
from __future__ import annotations
import json
import urllib.request
import uuid

from .config import load_config
from .security import SECRETS


def _post(url: str, payload: dict, headers: dict | None = None, timeout: float = 10.0):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json; charset=utf-8")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get(url: str, headers: dict | None = None, timeout: float = 10.0):
    req = urllib.request.Request(url, method="GET")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _credentials() -> tuple[str, str] | None:
    cfg = load_config()["feishu"]
    if not cfg.get("enabled") or not cfg.get("app_id"):
        return None
    secret = SECRETS.decrypt(cfg.get("app_secret_enc", ""))
    if not secret:
        secret = cfg.get("app_secret", "")
    return cfg["app_id"], secret


def status() -> dict:
    cfg = load_config()["feishu"]
    return {"enabled": bool(cfg.get("enabled")), "configured": bool(cfg.get("app_id")),
            "folder_token": cfg.get("folder_token", ""),
            "note": "需在飞书开放平台创建企业自建应用，开通云空间(drive)权限并把凭据写入设置；全程走 https，密钥仅加密存于本地。"}


def tenant_token() -> str:
    cred = _credentials()
    if not cred:
        raise RuntimeError("飞书未启用或未配置凭据")
    r = _post("https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
              {"app_id": cred[0], "app_secret": cred[1]})
    if r.get("code") != 0:
        raise RuntimeError(f"获取 tenant_access_token 失败：{r}")
    return r["tenant_access_token"]


def sync_file(local_path: str, name: str | None = None) -> dict:
    """一键同步本地文件到飞书云空间（先上传，返回 file_token；可再转在线文档）。"""
    import os
    cred = _credentials()
    if not cred:
        return {"ok": False, "error": "飞书接口未启用/未配置，已在本地保留文件（零泄露）"}
    token = tenant_token()
    path = local_path
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        content = f.read()
    boundary = "----lw" + uuid.uuid4().hex
    fname = name or os.path.basename(path)
    cfg = load_config()["feishu"]
    folder = cfg.get("folder_token", "")
    parts = []
    def field(k, v):
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode())
    field("file_name", fname)
    field("parent_type", "explorer")
    field("parent_node", folder)
    field("size", str(size))
    parts.append(
        (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{fname}\"\r\n"
         "Content-Type: application/octet-stream\r\n\r\n").encode() + content + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(parts)
    req = urllib.request.Request(
        "https://open.feishu.cn/open-apis/drive/v1/files/upload_all",
        data=body, method="POST")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        r = json.loads(resp.read().decode("utf-8"))
    return {"ok": r.get("code") == 0, "result": r, "name": fname}
