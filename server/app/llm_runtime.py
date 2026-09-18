# -*- coding: utf-8 -*-
"""内置本地大模型运行时（随安装包封入，无需用户另装 Ollama）。

- 运行时：llama.cpp 的 llama-server（CPU 版，resources/llm/bin），仅绑定 127.0.0.1；
- 模型：resources/llm/models/*.gguf（默认 Qwen2.5-3B-Instruct Q4_K_M，中文法律文本）；
- 对外暴露 OpenAI 兼容接口 /v1/chat/completions，由 llm.py / ai_hub.py 调用；
- 后端启动时在后台线程预热（加载模型需数十秒），不阻塞界面；全程离线、无任何外联。
"""
from __future__ import annotations
import os
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

from .config import RESOURCES_DIR, DATA_DIR

PORT = 8766
BASE_URL = f"http://127.0.0.1:{PORT}"
LOG_PATH = DATA_DIR / "llm-runtime.log"

_state = {"phase": "stopped", "proc": None, "model": "", "error": "", "started_at": ""}
_lock = threading.Lock()


# ---- Windows 作业对象：后端进程无论正常退出还是被强杀，llama-server 都随之消亡，不残留 ----
def _make_kill_job():
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)

        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
                        ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
                        ("LimitFlags", wintypes.DWORD),
                        ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t),
                        ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_void_p),
                        ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [(n, wintypes.ULARGE_INTEGER) for n in
                        ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                         "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                        ("IoInfo", IO_COUNTERS),
                        ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
        h = k32.CreateJobObjectW(None, None)
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        k32.SetInformationJobObject(h, 9, ctypes.byref(info),
                                    ctypes.sizeof(JOBOBJECT_EXTENDED_LIMIT_INFORMATION))
        return h
    except Exception:
        return None


_job = _make_kill_job()


def _assign_job(proc: subprocess.Popen):
    if _job is None or sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.WinDLL("kernel32", use_last_error=True).AssignProcessToJobObject(
            _job, int(proc._handle))
    except Exception:
        pass
# -----------------------------------------------------------------------------------------


def _candidates() -> tuple[Path | None, Path | None]:
    root = RESOURCES_DIR / "llm"
    # llama.cpp 发行包的可执行文件名按平台区分：Windows 为 llama-server.exe，macOS / Linux 无后缀
    names = ("llama-server.exe", "llama-server") if sys.platform == "win32" else ("llama-server",)
    exe = None
    for name in names:
        cand = root / "bin" / name
        if cand.exists():
            exe = cand
            break
    models = sorted((root / "models").glob("*.gguf")) if (root / "models").exists() else []
    return exe, (models[0] if models else None)


def available() -> bool:
    exe, model = _candidates()
    return bool(exe and model)


def model_name() -> str:
    _, model = _candidates()
    return model.stem if model else ""


def _proc_alive() -> bool:
    p = _state["proc"]
    return p is not None and p.poll() is None


def _health_ok(timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(f"{BASE_URL}/health", timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def _warmup(proc: subprocess.Popen):
    """等待模型加载完成（llama-server 先监听端口、加载完才返回 health=ok）。"""
    deadline = time.time() + 300
    while time.time() < deadline:
        if proc.poll() is not None:
            _state.update(phase="failed", error="推理进程提前退出，请查看 data/llm-runtime.log")
            return
        if _health_ok():
            _state.update(phase="running")
            return
        time.sleep(1.0)
    _state.update(phase="failed", error="模型加载超时（5 分钟）")


def ensure_running(wait: bool = False) -> dict:
    """确保内置推理服务运行；后台预热，立即返回状态。"""
    with _lock:
        if _state["phase"] == "running" and _proc_alive() and _health_ok():
            return status()
        if _state["phase"] == "starting" and _proc_alive():
            return status()
        exe, model = _candidates()
        if not exe:
            _state.update(phase="missing", error="未找到内置 llama-server")
            return status()
        if not model:
            _state.update(phase="missing", error="未找到内置模型 gguf")
            return status()
        threads = max(2, min(16, (os.cpu_count() or 4) * 3 // 4))
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        logf = open(LOG_PATH, "ab")
        kw = {"creationflags": 0x08000000} if sys.platform == "win32" else {}
        args = [str(exe), "-m", str(model), "--host", "127.0.0.1", "--port", str(PORT),
                "--ctx-size", "4096", "--threads", str(threads), "--n-gpu-layers", "0",
                "--parallel", "1", "--jinja", "--no-webui"]
        try:
            proc = subprocess.Popen(args, cwd=str(exe.parent), stdout=logf,
                                    stderr=subprocess.STDOUT, **kw)
            _assign_job(proc)
        except Exception as e:
            _state.update(phase="failed", error=f"启动失败：{e}")
            return status()
        _state.update(phase="starting", proc=proc, model=model.name,
                      error="", started_at=time.strftime("%Y-%m-%d %H:%M:%S"))
    t = threading.Thread(target=_warmup, args=(proc,), daemon=True)
    t.start()
    if wait:
        t.join()
    return status()


def stop():
    p = _state.get("proc")
    if p and p.poll() is None:
        p.terminate()
        try:
            p.wait(timeout=5)
        except Exception:
            p.kill()
    _state.update(phase="stopped", proc=None)


def status() -> dict:
    phase = _state["phase"]
    if phase in ("running", "starting") and not _proc_alive():
        phase = "stopped"
    return {"available": available(), "phase": phase, "base_url": BASE_URL,
            "model": _state.get("model") or model_name(), "error": _state.get("error", ""),
            "started_at": _state.get("started_at", "")}
