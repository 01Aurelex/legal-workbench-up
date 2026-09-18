# -*- coding: utf-8 -*-
"""授权与激活（一机一码，离线校验）。

设计：
- 机器指纹 = Windows MachineGuid + CPU ID + 首硬盘序列号 的 SHA-256，重装软件不变、换机即变；
- 激活码 = Ed25519 签名的载荷（内嵌机器指纹），客户端只内置【公钥】，
  私钥仅由 license-admin 签发后端持有，因此即使逆向客户端也无法伪造激活码；
- 未激活时仅【案件管理】可用（见 API_ALLOWED），其余接口返回 403 锁定；
- 全部校验离线完成，激活后无需联网；授权文件 data/.license 仅保存签名串，篡改即失效。
"""
from __future__ import annotations
import base64
import hashlib
import json
import os
import subprocess
import sys
from datetime import date

from .config import DATA_DIR
from .db import audit

# 签发后端 Ed25519 公钥（原始 32 字节，hex）。私钥不在客户端、不随安装包分发。
PUBLIC_KEY_HEX = "d36cdd8c9e092036e88bd4f10f33daa27eb081a44ca27dbf5e72979f48fa3001"
LICENSE_PATH = DATA_DIR / ".license"
FREE_EDITION = "free"
PRO_EDITION = "pro"

_FP_CACHE: dict = {}

# ========================= 机器指纹 =========================
def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64u_dec(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def machine_code() -> str:
    """用户可见、可复制给签发方的机器码。

    即完整机器指纹的 base64url（分组便于抄写），签发端可无损还原指纹，
    因此激活码与本机严格绑定（一机一码）。
    """
    raw = bytes.fromhex(machine_fingerprint())
    s = _b64u(raw)
    return " ".join(s[i:i + 6] for i in range(0, len(s), 6))


def decode_machine_code(code: str) -> str:
    """签发端/校验端：把用户回传的机器码还原为 64 位 hex 指纹（容忍空白/横线）。"""
    s = "".join((code or "").split())
    return _b64u_dec(s).hex()


def _registry_machine_guid() -> str:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SOFTWARE\Microsoft\Cryptography") as k:
            v, _ = winreg.QueryValueEx(k, "MachineGuid")
            return str(v).strip()
    except Exception:
        return ""


def _powershell_hardware() -> tuple[str, str]:
    """一次 PowerShell 调用同时取 CPU ID 与首硬盘序列号（约 1 秒，仅启动时调用）。"""
    ps = ("$c=(Get-CimInstance Win32_Processor | Select-Object -First 1).ProcessorId;"
          "$d=(Get-CimInstance Win32_DiskDrive -Filter 'Index=0' | Select-Object -First 1).SerialNumber;"
          "Write-Output ($c+'|'+$d)")
    try:
        kw = {"creationflags": 0x08000000} if sys.platform == "win32" else {}
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                           capture_output=True, text=True, timeout=8, **kw)
        line = (r.stdout or "").strip().splitlines()[-1] if r.stdout else ""
        c, _, d = line.partition("|")
        return c.strip(), d.strip()
    except Exception:
        return "", ""


def machine_fingerprint() -> str:
    """返回 64 位 hex 机器指纹（稳定标识本机）。"""
    if _FP_CACHE.get("hash"):
        return _FP_CACHE["hash"]
    guid = _registry_machine_guid()
    cpu, disk = _powershell_hardware()
    raw = "||".join([guid, cpu.replace(" ", ""), disk.replace(" ", ""),
                     os.environ.get("COMPUTERNAME", "")])
    h = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    _FP_CACHE["hash"] = h
    return h


# ========================= 激活码签名校验 =========================
def _public_key():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    return Ed25519PublicKey.from_public_bytes(bytes.fromhex(PUBLIC_KEY_HEX))


def sign_payload(payload: dict, private_pem: bytes) -> str:
    """仅签发端使用：用 Ed25519 私钥对载荷签名，返回激活码字符串。"""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization
    priv = serialization.load_pem_private_key(private_pem, password=None)
    assert isinstance(priv, Ed25519PrivateKey)
    body = _b64u(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    sig = priv.sign(body.encode("ascii"))
    return body + "." + _b64u(sig)


def verify_code(code: str) -> dict:
    """校验激活码：签名有效 + 绑定本机 + 未过期。返回 (payload, err)。"""
    code = (code or "").strip().replace(" ", "").replace("\n", "")
    if "." not in code:
        return {}
    body, sig = code.split(".", 1)
    try:
        payload = json.loads(_b64u_dec(body))
        _public_key().verify(_b64u_dec(sig), body.encode("ascii"))
    except Exception:
        raise ValueError("激活码签名无效，请勿手工修改或使用其他软件的激活码")
    if payload.get("v") != 1:
        raise ValueError("激活码版本不受支持")
    if payload.get("m") != machine_fingerprint():
        raise ValueError("激活码与本机不匹配（一机一码），请用本机机器码重新申领")
    exp = (payload.get("exp") or "").strip()
    if exp and exp < date.today().isoformat():
        raise ValueError("激活码已到期")
    return payload


def _saved_code() -> str:
    try:
        return LICENSE_PATH.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def license_status() -> dict:
    fp = machine_fingerprint()
    out = {"activated": False, "edition": FREE_EDITION, "machine_code": machine_code(),
           "expiry": "", "activated_at": "", "note": "", "reason": ""}
    code = _saved_code()
    if not code:
        return out
    try:
        p = verify_code(code)
        out.update(activated=True, edition=p.get("e", PRO_EDITION), expiry=p.get("exp", ""),
                   activated_at=p.get("iat", ""), note=p.get("note", ""))
    except ValueError as e:
        out["reason"] = str(e)
    return out


def activate(code: str) -> dict:
    payload = verify_code(code)  # 无效直接抛 ValueError
    LICENSE_PATH.write_text(code.strip(), encoding="utf-8")
    try:
        os.chmod(LICENSE_PATH, 0o600)
    except OSError:
        pass
    audit("授权激活", f"版本 {payload.get('e')} 到期 {payload.get('exp') or '永久'}")
    return license_status()


# ========================= 未激活功能门控 =========================
# 未激活（免费版）仅开放【案件管理】所需接口 + 软件自身运行必需接口。
# 案件管理依赖：案件 CRUD、案件类型、要素式文书模板、导航外壳、授权自身、静态资源。
_ALLOW_EXACT = {"/api/bootstrap", "/api/health", "/api/license/status",
                "/api/license/activate", "/api/nav", "/api/archive/open"}
_ALLOW_PREFIX = ("/api/cases", "/api/case/", "/api/case-types", "/api/doc-templates",
                 "/api/license", "/api/flow", "/api/workflow")
# 案件新建表单需要只读客户列表（客户的增删改仍锁定；客户由建案时服务端自动建档）
_ALLOW_GET_PREFIX = ("/api/clients",)


def api_allowed(path: str, method: str) -> bool:
    """未激活状态下，该 API 是否放行。激活后全部放行。"""
    if license_status()["activated"]:
        return True
    if path in _ALLOW_EXACT:
        return True
    if path.startswith(_ALLOW_PREFIX):
        return True
    if method == "GET" and path.startswith(_ALLOW_GET_PREFIX):
        return True
    return False
