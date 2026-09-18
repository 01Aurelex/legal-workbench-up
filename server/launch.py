# -*- coding: utf-8 -*-
"""本地工作台启动器：自动安装依赖 -> 启动仅监听 127.0.0.1 的服务 -> 打开浏览器。"""
from __future__ import annotations
import os
import sys
import threading
import time
import webbrowser

# Windows 非中文区域设置下强制 UTF-8 模式，保证中文文件名/案卷内容不出错
if not sys.flags.utf8_mode:
    os.environ["PYTHONUTF8"] = "1"
    os.execv(sys.executable, [sys.executable] + sys.argv)

from server.app.config import load_config
from server.app.security import get_or_create_token


def main():
    cfg = load_config()
    host, port = cfg["host"], cfg["port"]
    token = get_or_create_token()
    url = f"http://{host}:{port}/?token={token}"

    def _open():
        time.sleep(1.5)
        webbrowser.open(url)

    threading.Thread(target=_open, daemon=True).start()
    print("=" * 64)
    print(" 律师本地工作台（预览版）已启动，仅监听本机回环地址")
    print(f" 访问地址: {url}")
    print(" 所有数据仅保存在本目录 data/ 下，关闭窗口即停止服务")
    print("=" * 64)
    import uvicorn
    # ws="none"：本应用没有任何 WebSocket 端点（前端只用 HTTP 轮询），必须显式关闭。
    # 否则 uvicorn 会加载 websockets 协议实现；若环境中残留残缺的 websockets
    # （只有 C 扩展、无 __init__.py），import 会"成功"为 namespace package，
    # 而 `from websockets import __version__` 抛 ImportError 且不被捕获，后端起不来。
    # 与 server/frozen_main.py 的冻结入口保持一致。
    uvicorn.run("server.app.main:app", host=host, port=port, log_level="warning", ws="none")


if __name__ == "__main__":
    sys.exit(main())
