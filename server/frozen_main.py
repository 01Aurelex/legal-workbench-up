# -*- coding: utf-8 -*-
"""PyInstaller 冻结入口（免安装测试版 / Tauri sidecar 共用）。
- 数据、配置、密钥、数据库全部写在 exe 同级 data/ 目录（见 config.py 冻结分支）；
- LW_NO_BROWSER=1 时不自动开浏览器（Tauri 外壳自带 webview）；
- LW_AUTO_TOKEN 由外壳注入时直接作为本机访问令牌。"""
from __future__ import annotations
import os
import sys
import threading
import time
import webbrowser


def _ensure_utf8() -> None:
    # 冻结后无法 os.execv 重启自身，直接用 UTF-8 模式兜底（PyInstaller 以 -X utf8 打包）
    if not sys.flags.utf8_mode:
        os.environ["PYTHONUTF8"] = "1"


def _write_crash(text: str) -> None:
    """windowed（无控制台）模式下用户只看得到一句弹窗提示，把完整栈落到文件便于排查。"""
    targets = []
    try:
        from server.app.config import DATA_DIR
        targets.append(DATA_DIR / "startup_error.log")
    except Exception:
        pass
    if getattr(sys, "frozen", False):
        targets.append(os.path.join(os.path.dirname(sys.executable), "startup_error.log"))
    else:
        targets.append(os.path.join(os.getcwd(), "startup_error.log"))
    for p in targets:
        try:
            with open(p, "a", encoding="utf-8") as f:
                f.write("\n" + "=" * 64 + "\n")
                f.write(time.strftime("%Y-%m-%d %H:%M:%S") + "\n")
                f.write(text)
            return
        except Exception:
            continue


def main() -> int:
    _ensure_utf8()
    # windowed（无控制台）模式下 sys.stdout/stderr 为 None，重定向到日志文件，避免 uvicorn 写日志崩溃
    from server.app.config import DATA_DIR
    if sys.stdout is None or sys.stderr is None:
        log = open(DATA_DIR / "backend.log", "a", encoding="utf-8")
        sys.stdout = log
        sys.stderr = log
    # 延迟导入，确保环境变量先就位
    from server.app.config import load_config
    from server.app.security import get_or_create_token
    import uvicorn
    from server.app.main import app

    cfg = load_config()
    host, port = cfg["host"], cfg["port"]
    token = get_or_create_token()
    url = f"http://{host}:{port}/?token={token}"

    if not os.environ.get("LW_NO_BROWSER"):
        def _open():
            time.sleep(1.2)
            webbrowser.open(url)
        threading.Thread(target=_open, daemon=True).start()
        print("=" * 60)
        print(" 律师本地工作台（免安装测试版）已启动，仅监听 127.0.0.1")
        print(f" 访问地址: {url}")
        print(" 关闭本窗口即停止服务；数据全部在程序目录 data/ 下")
        print("=" * 60)
    # ws="none"：本应用不提供任何 WebSocket 端点（前端也只用 HTTP 轮询），
    # 必须显式关闭，否则 uvicorn 会尝试加载 websockets 协议实现——
    # 一旦包目录里残留残缺的 websockets（只有 C 扩展、无 __init__.py），
    # import websockets 会“成功”为 namespace package，而
    # `from websockets import __version__` 抛 ImportError 且不被 uvicorn 捕获
    # （uvicorn/protocols/websockets/auto.py:19 的 else 分支），导致后端起不来。
    uvicorn.run(app, host=host, port=port, log_level="warning", ws="none")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException:
        import traceback
        _write_crash(traceback.format_exc())
        raise
