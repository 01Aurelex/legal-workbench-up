# -*- coding: utf-8 -*-
"""运行时防护：反调试 / 完整性自校验 / 单实例。

本模块在打包时用 Cython 编译为原生机器码（.pyd / .so）后分发，
校验逻辑与密钥均不以 Python 源码形式存在于发行包中。
"""
from __future__ import annotations

# --------------------------------------------------------------------------
# 路径解析：默认值全部相对「本脚本所在仓库」，可用 LW_* 环境变量覆盖。
#   LW_SRC    源码根目录（含 server/ frontend/ data/），默认仓库根
#   LW_BUILD  构建工作目录，默认本脚本所在目录（<repo>/build）
#   LW_DIST   免安装发行版目录（可选，仅作前端回退来源）
# --------------------------------------------------------------------------
import os as _os
_LW_BUILD = _os.path.dirname(_os.path.abspath(__file__))
_LW_ROOT = _os.path.dirname(_LW_BUILD)
_LW_BUILD_SRC = _os.path.join(_LW_BUILD, "src")
_LW_BUILD_OUT = _os.path.join(_LW_BUILD, "out")
_LW_DIST = _os.path.join(_LW_ROOT, "dist", "legal-workbench")

import hashlib
import hmac
import json
import os
import socket
import sys
import time

_SALT_A = b"FaYan\x00LegalWorkbench"
_SALT_B = b"integrity\x00guard\x00v1"


def _key() -> bytes:
    """派生完整性校验密钥（结果仅在编译后的机器码中参与运算）。"""
    a = hashlib.sha512(_SALT_A + _SALT_B).digest()
    b = hashlib.sha256(bytes(i ^ 0x5A for i in a) + _SALT_A).digest()
    c = hashlib.sha384(b + _SALT_B + a[::-1]).digest()
    return hashlib.sha256(a + b + c).digest()


# ------------------------------------------------------------------ 反调试
def _dbg_windows() -> bool:
    try:
        import ctypes
        from ctypes import wintypes

        k = ctypes.windll.kernel32
        if k.IsDebuggerPresent():
            return True
        found = wintypes.BOOL(False)
        k.CheckRemoteDebuggerPresent(k.GetCurrentProcess(), ctypes.byref(found))
        if found.value:
            return True
        # NtQueryInformationProcess：ProcessDebugPort(7) / ProcessDebugObjectHandle(30)
        ntdll = ctypes.windll.ntdll
        for info in (7, 30):
            buf = ctypes.c_void_p(0)
            st = ntdll.NtQueryInformationProcess(
                k.GetCurrentProcess(), info, ctypes.byref(buf),
                ctypes.sizeof(buf), None)
            if st == 0 and buf.value:
                return True
    except Exception:
        return False
    return False


def _dbg_macos() -> bool:
    try:
        import ctypes
        libc = ctypes.CDLL("/usr/lib/libc.dylib", use_errno=True)
        # PT_DENY_ATTACH：主动拒绝调试器附加，同时使 gdb/lldb 无法挂载
        libc.ptrace(31, 0, 0, 0)
    except Exception:
        pass
    try:
        import ctypes
        libc = ctypes.CDLL("/usr/lib/libc.dylib", use_errno=True)
        mib = (ctypes.c_int * 4)(1, 14, 1, os.getpid())  # CTL_KERN, KERN_PROC, KERN_PROC_PID
        buf = ctypes.create_string_buffer(648)
        n = ctypes.c_size_t(648)
        if libc.sysctl(mib, 4, buf, ctypes.byref(n), None, 0) == 0:
            # kinfo_proc.kp_proc.p_flag：arm64/x86_64 下 extern_proc 起始为
            # __p_forw/__p_back（旧版）或 p_starttime（新版），此处按 32 字节偏移取 p_flag
            for off in (32, 28, 24):
                flag = int.from_bytes(buf[off:off + 4], "little")
                if flag & 0x00000800:  # P_TRACED
                    return True
    except Exception:
        pass
    return False


def _dbg_linux() -> bool:
    try:
        st = open("/proc/self/status", encoding="utf-8", errors="ignore").read()
        for line in st.splitlines():
            if line.startswith("TracerPid:"):
                return int(line.split()[1]) != 0
    except Exception:
        pass
    return False


def _being_debugged() -> bool:
    if sys.platform == "win32":
        return _dbg_windows()
    if sys.platform == "darwin":
        return _dbg_macos()
    return _dbg_linux()


def arm() -> None:
    """最早执行的防护：发现调试器立即静默退出。"""
    if os.environ.get("LW_ALLOW_DEBUG"):
        return
    if _being_debugged():
        time.sleep(0.4)
        os._exit(9)


# ------------------------------------------------------------------ 完整性
def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_integrity(base: str) -> bool:
    """校验打包产物未被篡改。无清单（未生成）时放行，避免误伤。"""
    if not base or not os.path.isdir(base):
        return True
    mp = os.path.join(base, "integrity.json")
    if not os.path.isfile(mp):
        return True
    try:
        with open(mp, "r", encoding="utf-8") as f:
            doc = json.load(f)
        items = doc.get("files") or {}
        sig = doc.get("sig") or ""
        payload = json.dumps(items, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if not hmac.compare_digest(hmac.new(_key(), payload, hashlib.sha256).hexdigest(), sig):
            return False
        for rel, want in items.items():
            p = os.path.join(base, rel)
            if not os.path.isfile(p):
                return False
            if not hmac.compare_digest(_sha256_file(p), want):
                return False
    except Exception:
        return False
    return True


# ------------------------------------------------------------------ 单实例
def single_instance(host: str, port: int) -> bool:
    """端口已被本程序占用时提示并退出，避免多开导致数据竞争。"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((host, int(port)))
        s.close()
        return True
    except OSError:
        try:
            s.close()
        except Exception:
            pass
        return False


# ------------------------------------------------------------------ 提示
def alert(msg: str) -> None:
    """无控制台环境下的提示（Windows 弹窗 / macOS 通知 / 其余写日志）。"""
    try:
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, msg, "法岩律师本地工作台", 0x10)
            return
        if sys.platform == "darwin":
            os.system("osascript -e 'display dialog \"%s\" with title \"法岩律师本地工作台\" buttons {\"确定\"} with icon stop'"
                      % msg.replace('"', "'").replace("\n", " "))
            return
    except Exception:
        pass
    sys.stderr.write(msg + "\n")
