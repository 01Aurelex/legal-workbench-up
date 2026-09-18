# -*- coding: utf-8 -*-
"""本地文件监听（需求12）：外部修改已生成文书/笔记 -> 与系统记录比对 -> 生成待同步提示。
优先 watchdog，无该依赖时退化为 10 秒轮询，保证预览版无额外依赖也能运行。"""
from __future__ import annotations
import threading
import time

from . import db, docgen, vault
from .config import VAULT_DIR

_state = {"thread": None, "stop": False}


def _tick():
    docgen.rescan_disk_state()
    # Markdown 笔记：以 mtime/sha 比对索引，发现外部改动则登记提醒
    for r in db.query("SELECT rel_path,mtime,sha256 FROM files"):
        p = VAULT_DIR / r["rel_path"]
        if not p.exists():
            continue
        if p.stat().st_mtime > (r["mtime"] or 0) + 1:
            text = p.read_text(encoding="utf-8")
            import hashlib
            h = hashlib.sha256(text.encode("utf-8")).hexdigest()
            if h != r["sha256"]:
                exists = db.query_one(
                    "SELECT id FROM reminders WHERE kind='文档同步' AND ref=? AND done=0",
                    (r["rel_path"],))
                if not exists:
                    db.execute(
                        "INSERT INTO reminders(kind,title,detail,due,level,ref,created) VALUES(?,?,?,?,?,?,?)",
                        ("文档同步", f"本地笔记被外部修改：{r['rel_path']}",
                         "系统检测到档案库中的文件在工作台之外被修改，是否以磁盘版本同步系统索引？",
                         time.strftime("%Y-%m-%d"), "普通", r["rel_path"], db.now()))
                vault.scan_file(p)


def _poll_loop():
    while not _state["stop"]:
        try:
            _tick()
        except Exception:
            pass
        time.sleep(10)


def start():
    if _state["thread"] and _state["thread"].is_alive():
        return
    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler

        class H(FileSystemEventHandler):
            def on_any_event(self, event):
                if not event.is_directory and event.src_path.endswith((".md", ".docx")):
                    _tick()
        obs = Observer()
        obs.schedule(H(), str(VAULT_DIR), recursive=True)
        obs.start()
        _state["observer"] = obs
    except Exception:
        pass
    _state["stop"] = False
    t = threading.Thread(target=_poll_loop, daemon=True)
    t.start()
    _state["thread"] = t


def stop():
    _state["stop"] = True
    obs = _state.get("observer")
    if obs:
        obs.stop()
