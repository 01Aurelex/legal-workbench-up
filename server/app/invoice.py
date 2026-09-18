# -*- coding: utf-8 -*-
"""发票管理：邮箱自动收取 → 按日期归档到本地 → 微信公众号推送告知。

实现要点
- 纯标准库 imaplib/email 实现 IMAP 收取，不引入第三方邮件库；
- 只读取配置目录内、指定天数内（默认30天）的邮件，跳过已归档附件（按 sha256 去重）；
- 发票按开票日期归档到 data/invoices/YYYY-MM/，文件名规范化为「日期_开票方_金额.扩展名」；
- 归档成功后写入 invoices 表，并按配置决定是否经微信公众号推送；
- 未配置邮箱时只支持手工导入，不发起任何外网请求。
"""
from __future__ import annotations
import email
import hashlib
import imaplib
import io
import os
import re
import time
from datetime import datetime, timedelta
from email.header import decode_header, make_header
from pathlib import Path

from .config import DATA_DIR, load_config, save_config
from .security import SECRETS
from . import db

INVOICE_DIR = DATA_DIR / "invoices"
INVOICE_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_KEYWORDS = "发票,invoice,增值税,电子发票,开票"
ATT_EXT = {".pdf", ".ofd", ".jpg", ".jpeg", ".png", ".zip", ".xml"}

AMOUNT_PATTERNS = [
    r"(?:小写|价税合计|合计金额|金额|总计)[^\d\-]{0,8}([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,2})?)",
    r"(?:￥|¥|RMB|rmb|人民币)\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,2})?)",
    r"\b([0-9]{1,3}(?:,[0-9]{3})*\.[0-9]{2})\b",
]
DATE_PATTERNS = [
    r"(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日",
    r"(20\d{2})[-/](\d{1,2})[-/](\d{1,2})",
]
SELLER_PATTERNS = [
    r"(?:销售方|销\s*售\s*方|开票方|开票单位)[^\n:：]{0,6}[:：]\s*([^\s，,。;\n]{2,40})",
    r"([^\s，,。;\n]{2,40}(?:有限公司|股份公司|有限责任公司|事务所|中心|商行|个体户))",
]


# ---------------- 配置 ----------------
def _cfg() -> dict:
    return load_config().get("invoice", {}) or {}


def _password(cfg: dict) -> str:
    return SECRETS.decrypt(cfg.get("password_enc", "")) or cfg.get("password", "")


def status() -> dict:
    cfg = _cfg()
    return {
        "enabled": bool(cfg.get("enabled")),
        "configured": bool(cfg.get("username")) and bool(_password(cfg)),
        "imap_host": cfg.get("imap_host", ""),
        "imap_port": cfg.get("imap_port", 993),
        "username": cfg.get("username", ""),
        "folder": cfg.get("folder", "INBOX"),
        "days": cfg.get("days", 30),
        "only_unseen": bool(cfg.get("only_unseen", True)),
        "keywords": cfg.get("keywords", DEFAULT_KEYWORDS),
        "auto_notify": bool(cfg.get("auto_notify", True)),
        "interval_minutes": cfg.get("interval_minutes", 30),
        "last_checked": db.kv_get("invoice_last_checked", ""),
        "dir": str(INVOICE_DIR),
        "secret_store": {"available": SECRETS.available},
    }


def save_settings(patch: dict) -> dict:
    cfg = load_config()
    inv = cfg.setdefault("invoice", {})
    for k in ("enabled", "imap_host", "imap_port", "imap_ssl", "username",
              "folder", "days", "only_unseen", "keywords", "auto_notify",
              "interval_minutes"):
        if k in patch:
            inv[k] = patch[k]
    if patch.get("password"):
        if not SECRETS.available:
            raise RuntimeError("加密组件不可用，为防泄露已拒绝保存邮箱密码")
        inv["password_enc"] = SECRETS.encrypt(patch["password"])
    inv.pop("password", None)
    save_config(cfg)
    db.audit("修改发票邮箱设置", inv.get("username", ""))
    return status()


# ---------------- 列表与查询 ----------------
def list_invoices(keyword: str = "", month: str = "", limit: int = 500) -> list[dict]:
    sql = "SELECT * FROM invoices WHERE 1=1"
    args: list = []
    if month:
        sql += " AND month_dir=?"; args.append(month)
    if keyword:
        sql += " AND (file_name LIKE ? OR sender LIKE ? OR subject LIKE ? OR note LIKE ?)"
        args += [f"%{keyword}%"] * 4
    sql += " ORDER BY invoice_date DESC, id DESC LIMIT ?"
    args.append(limit)
    return db.query(sql, tuple(args))


def stats() -> dict:
    rows = db.query("SELECT month_dir, COUNT(*) c, COALESCE(SUM(amount),0) s "
                    "FROM invoices GROUP BY month_dir ORDER BY month_dir DESC")
    total_amount = db.query_one("SELECT COALESCE(SUM(amount),0) s FROM invoices")["s"] or 0
    total_count = db.query_one("SELECT COUNT(*) c FROM invoices")["c"] or 0
    return {"count": total_count, "total_amount": round(total_amount, 2),
            "by_month": [{"month": r["month_dir"] or "未归类", "count": r["c"],
                          "amount": round(r["s"], 2)} for r in rows]}


def update_note(iid: int, note: str) -> dict:
    db.execute("UPDATE invoices SET note=? WHERE id=?", (note, iid))
    return db.query_one("SELECT * FROM invoices WHERE id=?", (iid,))


def delete_invoice(iid: int, remove_file: bool = False) -> dict:
    row = db.query_one("SELECT * FROM invoices WHERE id=?", (iid,))
    if not row:
        raise ValueError("发票不存在")
    if remove_file and row["file_path"] and Path(row["file_path"]).exists():
        try:
            Path(row["file_path"]).unlink()
        except OSError:
            pass
    db.execute("DELETE FROM invoices WHERE id=?", (iid,))
    db.audit("删除发票", row["file_name"] or str(iid))
    return {"ok": True}


# ---------------- 文本解析 ----------------
def _decode_mime(value: str) -> str:
    try:
        return str(make_header(decode_header(value or "")))
    except Exception:
        return value or ""


def _first_match(patterns: list[str], text: str) -> str:
    for p in patterns:
        m = re.search(p, text)
        if m:
            if len(m.groups()) == 3:
                y, mo, d = m.group(1), int(m.group(2)), int(m.group(3))
                try:
                    return datetime(int(y), mo, d).strftime("%Y-%m-%d")
                except ValueError:
                    continue
            return m.group(1).strip()
    return ""


def parse_invoice_text(text: str) -> dict:
    flat = re.sub(r"\s+", " ", text or "")
    amount_raw = _first_match(AMOUNT_PATTERNS, flat)
    amount = 0.0
    if amount_raw:
        try:
            amount = float(amount_raw.replace(",", ""))
        except ValueError:
            amount = 0.0
    return {"amount": round(amount, 2),
            "invoice_date": _first_match(DATE_PATTERNS, flat),
            "seller": _first_match(SELLER_PATTERNS, flat)}


def _extract_pdf_text(data: bytes) -> str:
    """可选增强：装了 pdfplumber 时提取 PDF 文本辅助识别金额与开票方。"""
    try:
        import pdfplumber  # type: ignore
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            return "\n".join((p.extract_text() or "") for p in pdf.pages[:2])
    except Exception:
        return ""


# ---------------- 归档 ----------------
def _safe_name(s: str, maxlen: int = 40) -> str:
    s = re.sub(r'[\\/:*?"<>|\r\n\t]', "", (s or "").strip())
    return s[:maxlen] or "未命名"


def archive_file(data: bytes, filename: str, sender: str, subject: str,
                 source: str = "email", amount: float | None = None,
                 invoice_date: str | None = None, note: str = "") -> dict:
    """把一份发票附件落盘归档并登记到 invoices 表（按 sha256 去重）。"""
    sha = hashlib.sha256(data).hexdigest()
    if db.query_one("SELECT id FROM invoices WHERE sha256=?", (sha,)):
        return {"ok": False, "skipped": True, "reason": "该发票已归档（内容重复）"}

    ext = Path(filename).suffix.lower()
    text_hint = ""
    if ext == ".pdf":
        text_hint = _extract_pdf_text(data)

    parsed = parse_invoice_text(f"{subject}\n{text_hint}")
    amount = amount if amount is not None else parsed["amount"]
    invoice_date = (invoice_date or parsed["invoice_date"]
                    or datetime.now().strftime("%Y-%m-%d"))
    seller = _safe_name(sender or parsed["seller"] or "未知开票方")

    month_dir = invoice_date[:7].replace("/", "-") or datetime.now().strftime("%Y-%m")
    target_dir = INVOICE_DIR / month_dir
    target_dir.mkdir(parents=True, exist_ok=True)

    date_part = invoice_date.replace("-", "")
    amount_part = f"{amount:.2f}" if amount else "0.00"
    base = f"{date_part}_{seller}_{amount_part}"
    target = target_dir / f"{base}{ext}"
    n = 1
    while target.exists():
        target = target_dir / f"{base}_{n}{ext}"
        n += 1
    target.write_bytes(data)

    rel = f"invoices/{month_dir}/{target.name}"
    iid = db.insert("invoices", {
        "file_name": target.name, "file_path": str(target), "rel_path": rel,
        "sender": seller, "subject": (subject or "")[:200],
        "amount": amount, "invoice_date": invoice_date,
        "received_at": db.now(), "source": source, "month_dir": month_dir,
        "sha256": sha, "ext": ext, "notified": 0, "note": note or "",
        "created": db.now(),
    })
    db.audit("归档发票", f"{target.name}（{seller} {amount}）")
    return {"ok": True, "id": iid, "file_name": target.name,
            "rel_path": rel, "amount": amount,
            "invoice_date": invoice_date, "sender": seller}


# ---------------- IMAP 收取 ----------------
def _keywords(cfg: dict) -> list[str]:
    raw = cfg.get("keywords") or DEFAULT_KEYWORDS
    return [k.strip().lower() for k in raw.replace("，", ",").split(",") if k.strip()]


def _match_keyword(subject: str, filename: str, keywords: list[str]) -> bool:
    hay = f"{subject} {filename}".lower()
    if not keywords:
        return True
    return any(k in hay for k in keywords)


def fetch_from_mailbox(limit: int = 50) -> dict:
    """连接邮箱抓取发票附件并归档。未配置/失败时返回明确状态，不影响其他功能。"""
    cfg = _cfg()
    if not cfg.get("enabled"):
        return {"ok": False, "error": "发票邮箱收取未启用"}
    pwd = _password(cfg)
    if not cfg.get("username") or not pwd:
        return {"ok": False, "error": "请先配置邮箱账号与授权码/密码"}
    if not SECRETS.available and not cfg.get("password"):
        return {"ok": False, "error": "加密组件不可用，无法读取已保存的邮箱密码"}

    host = cfg.get("imap_host", "")
    port = int(cfg.get("imap_port", 993) or 993)
    folder = cfg.get("folder", "INBOX")
    days = int(cfg.get("days", 30) or 30)
    keywords = _keywords(cfg)
    since = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")

    saved, scanned, errors = [], 0, []
    client = None
    try:
        client = imaplib.IMAP4_SSL(host, port) if cfg.get("imap_ssl", True) else imaplib.IMAP4(host, port)
        client.login(cfg["username"], pwd)
        typ, _ = client.select(folder, readonly=True)
        if typ != "OK":
            return {"ok": False, "error": f"无法打开邮箱文件夹：{folder}"}
        criteria = f'(SINCE "{since}")'
        if cfg.get("only_unseen", True):
            criteria = f'(UNSEEN SINCE "{since}")'
        typ, data = client.search(None, criteria)
        if typ != "OK":
            return {"ok": False, "error": "邮件检索失败"}
        ids = (data[0].split() if data and data[0] else [])[-limit:]
        for mid in ids:
            try:
                typ, msg_data = client.fetch(mid, "(RFC822)")
                if typ != "OK" or not msg_data or not msg_data[0]:
                    continue
                msg = email.message_from_bytes(msg_data[0][1])
                scanned += 1
                subject = _decode_mime(msg.get("Subject", ""))
                sender = _decode_mime(msg.get("From", ""))
                sender_name = sender.split("<")[0].strip() or sender
                for part in msg.walk():
                    if part.get_content_maintype() == "multipart":
                        continue
                    filename = _decode_mime(part.get_filename() or "")
                    if not filename:
                        continue
                    ext = Path(filename).suffix.lower()
                    if ext not in ATT_EXT:
                        continue
                    if not _match_keyword(subject, filename, keywords):
                        continue
                    payload = part.get_payload(decode=True)
                    if not payload:
                        continue
                    res = archive_file(payload, filename, sender_name, subject, "email")
                    if res.get("ok"):
                        saved.append(res)
                    elif not res.get("skipped"):
                        errors.append(f"{filename}: {res.get('reason') or res.get('error')}")
            except Exception as e:  # 单封失败不影响整体
                errors.append(f"邮件 {mid}: {e}")
    except Exception as e:
        db.audit("发票收取失败", str(e)[:200])
        return {"ok": False, "error": f"连接邮箱失败：{e}"}
    finally:
        if client:
            try:
                client.close(); client.logout()
            except Exception:
                pass

    db.kv_set("invoice_last_checked", db.now())
    notified = 0
    if saved and cfg.get("auto_notify", True):
        notified = notify_new(saved)
    db.audit("发票收取", f"扫描 {scanned} 封，归档 {len(saved)} 份")
    return {"ok": True, "scanned": scanned, "saved": saved,
            "errors": errors, "notified": notified, "checked_at": db.now()}


# ---------------- 微信推送 ----------------
def notify_new(saved: list[dict]) -> int:
    """把新归档的发票通过微信公众号推送给用户（未启用微信时只入本地队列）。"""
    from . import integrations_wechat as wechat
    from . import workflow
    n = 0
    for s in saved:
        content = (f"【新发票已归档】\n开票方：{s.get('sender','未知')}\n"
                   f"金额：¥{s.get('amount',0):.2f}\n"
                   f"开票日期：{s.get('invoice_date','')}\n"
                   f"已按日期保存至：{s.get('rel_path','')}")
        try:
            res = wechat.enqueue("", content)
            if res.get("channel") == "wechat":
                n += 1
                db.execute("UPDATE invoices SET notified=1 WHERE id=?", (s.get("id"),))
        except Exception:
            pass
        # 本地提醒中心同步留痕
        db.execute("INSERT INTO reminders(kind,title,detail,due,level,ref,created)"
                   " VALUES(?,?,?,?,?,?,?)",
                   ("发票", f"新发票：{s.get('sender','未知')} ¥{s.get('amount',0):.2f}",
                    f"已归档至 {s.get('rel_path','')}", db.today(), "普通",
                    s.get("rel_path", ""), db.now()))
    return n


def notify_manual(iid: int) -> dict:
    row = db.query_one("SELECT * FROM invoices WHERE id=?", (iid,))
    if not row:
        raise ValueError("发票不存在")
    n = notify_new([row])
    return {"ok": True, "notified": n}


# ---------------- 手工导入 ----------------
def import_local(data: bytes, filename: str, note: str = "") -> dict:
    return archive_file(data, filename, "", filename, "manual", note=note)
