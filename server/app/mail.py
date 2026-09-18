# -*- coding: utf-8 -*-
"""邮件提醒适配器（需求：日程支持邮件提醒）。

使用标准库 smtplib + email 发送提醒邮件（SMTP/SSL 或 STARTTLS）。
未配置时不发任何外网请求；凭据经 Fernet 加密存于本地 config。
"""
from __future__ import annotations
import smtplib
import ssl
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr

from .config import load_config
from .security import SECRETS


def status() -> dict:
    cfg = load_config().get("mail") or {}
    return {"enabled": bool(cfg.get("enabled")), "smtp_host": cfg.get("smtp_host", ""),
            "username": cfg.get("username", ""), "to_addr": cfg.get("to_addr", ""),
            "password_saved": bool(cfg.get("password_enc")),
            "note": "日程到期可通过 SMTP 发送邮件提醒；未配置时零外发"}


def _password(cfg: dict) -> str:
    return SECRETS.decrypt(cfg.get("password_enc", "")) or ""


def send(to: str, subject: str, content: str) -> dict:
    """发送提醒邮件，返回 {ok, ...}。"""
    cfg = load_config().get("mail") or {}
    if not cfg.get("enabled"):
        return {"ok": False, "error": "邮件提醒未启用"}
    if not cfg.get("smtp_host") or not cfg.get("username") or not _password(cfg):
        return {"ok": False, "error": "邮件服务未配置完整（SMTP 主机/账号/授权码）"}
    to_addr = (to or cfg.get("to_addr", "")).strip()
    if not to_addr:
        return {"ok": False, "error": "缺少收件人邮箱"}
    from_name = cfg.get("from_name", "法岩律师工作台")
    from_addr = cfg.get("username")

    msg = MIMEText(content, "plain", "utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = formataddr((str(Header(from_name, "utf-8")), from_addr))
    msg["To"] = to_addr

    host = cfg["smtp_host"]
    port = int(cfg.get("smtp_port", 465))
    use_ssl = bool(cfg.get("ssl", True))
    try:
        if use_ssl:
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, timeout=20, context=ctx) as s:
                s.login(from_addr, _password(cfg))
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=20) as s:
                s.ehlo()
                s.starttls(context=ssl.create_default_context())
                s.ehlo()
                s.login(from_addr, _password(cfg))
                s.send_message(msg)
        return {"ok": True, "to": to_addr}
    except Exception as e:
        return {"ok": False, "error": f"邮件发送失败：{e}"}
