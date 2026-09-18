# -*- coding: utf-8 -*-
"""首页统计：使用统计 / 案件统计 / 最近打开 / 最近添加 / 到期提醒。"""
from __future__ import annotations
from collections import Counter, defaultdict
from datetime import datetime, date, timedelta

from . import db


def _pct(part: int, whole: int) -> float:
    return round(part / whole * 100, 1) if whole else 0.0


def overview() -> dict:
    t = db.today()
    ym = t[:7]
    files = db.query_one("SELECT COUNT(*) c FROM doc_registry")["c"]
    notes = db.query_one("SELECT COUNT(*) c FROM files")["c"]
    links = db.query_one("SELECT COUNT(*) c FROM links")["c"]
    cases = db.query_one("SELECT COUNT(*) c FROM cases")["c"]
    clients = db.query_one("SELECT COUNT(*) c FROM files WHERE ftype='client'")["c"]
    docs = db.query_one("SELECT COUNT(*) c FROM gen_docs")["c"]
    new_files_month = db.query_one(
        "SELECT COUNT(*) c FROM doc_registry WHERE substr(created,1,7)=?", (ym,))["c"]
    opens_week = db.query_one(
        "SELECT COUNT(*) c FROM doc_registry WHERE last_open>=?",
        ((date.today() - timedelta(days=7)).strftime("%Y-%m-%d"),))["c"]
    ai_msgs = db.query_one("SELECT COUNT(*) c FROM ai_messages WHERE role='user'")["c"]
    ai_sessions = db.query_one("SELECT COUNT(*) c FROM ai_sessions")["c"]
    invoices = db.query_one("SELECT COUNT(*) c FROM invoices")["c"]

    # 近 14 天活跃度（按最近打开 + 创建）
    active = []
    for i in range(13, -1, -1):
        d = (date.today() - timedelta(days=i)).strftime("%Y-%m-%d")
        n1 = db.query_one("SELECT COUNT(*) c FROM doc_registry WHERE substr(last_open,1,10)=?", (d,))["c"]
        n2 = db.query_one("SELECT COUNT(*) c FROM doc_registry WHERE substr(created,1,10)=?", (d,))["c"]
        active.append({"date": d, "open": n1, "add": n2})
    return {
        "files": files, "notes": notes, "links": links, "cases": cases,
        "clients": clients, "docs": docs, "invoices": invoices,
        "new_files_month": new_files_month, "opens_week": opens_week,
        "ai_questions": ai_msgs, "ai_sessions": ai_sessions,
        "active_trend": active,
    }


def case_stats() -> dict:
    rows = db.query("SELECT * FROM cases")
    total = len(rows)
    by_type = Counter(r.get("case_type") or "未分类" for r in rows)
    by_cat = Counter(r.get("case_category") or "未分类" for r in rows)
    by_stage = Counter(r.get("stage") or "未设置" for r in rows)
    by_risk = Counter(r.get("risk_level") or "中" for r in rows)
    closed = sum(1 for r in rows if (r.get("stage") or "") in ("结案", "已结案"))
    ym = db.today()[:7]
    new_month = sum(1 for r in rows if (r.get("updated") or "").startswith(ym))
    fee_total = sum(float(r.get("fee_amount") or 0) for r in rows)
    fee_paid = sum(float(r.get("fee_paid") or 0) for r in rows)
    return {
        "total": total, "closed": closed, "ongoing": total - closed, "new_month": new_month,
        "fee_total": round(fee_total, 2), "fee_paid": round(fee_paid, 2),
        "fee_outstanding": round(max(fee_total - fee_paid, 0), 2),
        "by_type": [{"key": k, "count": v, "pct": _pct(v, total)}
                    for k, v in by_type.most_common(10)],
        "by_category": [{"key": k, "count": v, "pct": _pct(v, total)}
                        for k, v in by_cat.most_common()],
        "by_stage": [{"key": k, "count": v, "pct": _pct(v, total)}
                     for k, v in by_stage.most_common(8)],
        "by_risk": [{"key": k, "count": v} for k, v in by_risk.most_common()],
    }


def recent_open(limit: int = 8) -> list[dict]:
    return db.query("SELECT * FROM doc_registry WHERE last_open IS NOT NULL AND last_open!='' "
                    "ORDER BY last_open DESC LIMIT ?", (limit,))


def recent_add(limit: int = 8) -> list[dict]:
    return db.query("SELECT * FROM doc_registry ORDER BY created DESC, mtime DESC LIMIT ?", (limit,))


def due_soon(days: int = 30, limit: int = 12) -> list[dict]:
    today = date.today()
    end = (today + timedelta(days=days)).strftime("%Y-%m-%d")
    rows = db.query(
        "SELECT * FROM reminders WHERE done=0 AND due!='' AND due<=? ORDER BY due ASC LIMIT ?",
        (end, limit))
    out = []
    for r in rows:
        try:
            d = datetime.strptime(r["due"], "%Y-%m-%d").date()
            delta = (d - today).days
        except Exception:
            delta = 0
        out.append({**r, "delta": delta,
                    "urgency": "逾期" if delta < 0 else ("今天" if delta == 0 else
                                                        ("3天内" if delta <= 3 else "临近"))})
    return out


def dashboard() -> dict:
    return {
        "overview": overview(),
        "cases": case_stats(),
        "recent_open": recent_open(),
        "recent_add": recent_add(),
        "due": due_soon(),
        "today": db.today(),
    }


def activity(limit: int = 30) -> list[dict]:
    """跨模块最近动态，供首页时间线展示。"""
    out = []
    for r in db.query("SELECT title,rel_path,last_open,created FROM doc_registry "
                      "ORDER BY COALESCE(NULLIF(last_open,''), created) DESC LIMIT ?", (limit,)):
        out.append({"kind": "文档", "title": r["title"] or r["rel_path"],
                    "ref": r["rel_path"],
                    "at": r["last_open"] or r["created"]})
    for r in db.query("SELECT record_type,title,amount,fee_date FROM fee_records "
                      "ORDER BY created DESC LIMIT 10"):
        out.append({"kind": "创收", "title": f"{r['record_type']}·{r['title']} ¥{r['amount'] or 0:.2f}",
                    "ref": "", "at": r["fee_date"] or ""})
    for r in db.query("SELECT file_name,invoice_date FROM invoices ORDER BY created DESC LIMIT 10"):
        out.append({"kind": "发票", "title": r["file_name"], "ref": "", "at": r["invoice_date"] or ""})
    out = [o for o in out if o["at"]]
    out.sort(key=lambda x: x["at"], reverse=True)
    return out[:limit]
