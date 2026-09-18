# -*- coding: utf-8 -*-
"""后台定时任务：发票邮箱轮询、期限提醒重建、档案总表刷新、微信待发队列外发。

所有任务都是守护线程，随后端进程启停；未开启相关集成时对应任务自动空转，不发起外网请求。
"""
from __future__ import annotations
import threading
import time
import traceback

from . import db, workflow, archive, invoice
from . import integrations_wechat as wechat
from . import mail

_TASKS: list[tuple[str, int, object]] = []   # (name, interval_seconds, fn)
_RUNNING = False
_STATE: dict[str, dict] = {}


def _safe(name: str, fn):
    def wrapper():
        while True:
            time.sleep(1)
            try:
                res = fn()
                _STATE[name] = {"last_run": db.now(), "ok": True, "result": res}
            except Exception as e:
                _STATE[name] = {"last_run": db.now(), "ok": False,
                                "error": f"{e}"}
                db.audit("定时任务异常", f"{name}: {e}")
            interval = dict((n, i) for n, i, _ in _TASKS).get(name, 600)
            time.sleep(max(interval, 30))
    t = threading.Thread(target=wrapper, daemon=True, name=f"lw-{name}")
    t.start()


def _job_invoice():
    cfg = invoice._cfg()
    if not cfg.get("enabled"):
        return {"skipped": "未启用"}
    return invoice.fetch_from_mailbox()


def _job_reminders():
    n = workflow.rebuild_case_reminders()
    c = wechat.flush_due_reminders()
    return {"reminders": n, "queued": c}


def _job_registry():
    return archive.sync_registry()


def _job_outbox():
    from .config import load_config
    if not load_config().get("wechat", {}).get("enabled"):
        return {"skipped": "微信未启用"}
    rows = db.query("SELECT id FROM outbox WHERE status='待发送' ORDER BY id LIMIT 20")
    sent = 0
    for r in rows:
        try:
            if wechat.send_one(r["id"]).get("ok"):
                sent += 1
        except Exception:
            pass
    return {"sent": sent, "pending": len(rows)}


def _job_schedule():
    """日程待办到期提醒：按 remind 通道发送邮件 / 微信，每条只提醒一次。"""
    today = db.today()
    rows = db.query("SELECT * FROM tasks WHERE done=0 AND reminded=0 AND remind!='' AND due!='' AND due<=?",
                    (today,))
    emailed = 0
    queued = 0
    for t in rows:
        channel = t.get("remind") or ""
        content = f"【日程提醒】{t['title']}（{t['due']} {t.get('kind','')}）{('：'+t['detail']) if t.get('detail') else ''}"
        if channel in ("email", "both"):
            r = mail.send(t.get("email") or "", f"日程提醒：{t['title']}", content)
            if r.get("ok"):
                emailed += 1
        if channel in ("wechat", "both"):
            from .config import load_config
            cfg = load_config()["wechat"]
            db.execute("INSERT INTO outbox(channel,target,content,status,created) VALUES(?,?,?,?,?)",
                       ("wechat" if cfg.get("enabled") else "local",
                        cfg.get("default_openid", ""), content, "待发送", db.now()))
            queued += 1
        db.execute("UPDATE tasks SET reminded=1 WHERE id=?", (t["id"],))
    return {"emailed": emailed, "queued": queued}


def start():
    global _RUNNING
    if _RUNNING:
        return
    _RUNNING = True
    _TASKS.extend([
        ("invoice", 30 * 60, _job_invoice),
        ("reminders", 20 * 60, _job_reminders),
        ("registry", 10 * 60, _job_registry),
        ("outbox", 10 * 60, _job_outbox),
        ("schedule", 10 * 60, _job_schedule),
    ])
    for name, interval, fn in _TASKS:
        _safe(name, fn)
    db.audit("调度器启动", f"{len(_TASKS)} 个后台任务")


def state() -> dict:
    return {"running": _RUNNING, "tasks": [
        {"name": n, "interval": i, **(_STATE.get(n, {"last_run": "", "ok": None}))}
        for n, i, _ in _TASKS]}
