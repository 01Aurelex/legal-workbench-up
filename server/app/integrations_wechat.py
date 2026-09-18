# -*- coding: utf-8 -*-
"""微信公众号提醒适配器（需求3）——无自有服务器的“纯出方向”实现。

关键事实（已核证微信官方文档）：
1. 本机只主动调用微信 API 出站发送（换 access_token、发消息），**不需要公网服务器/回调**；
   只有“被动接收用户消息”才必须配置服务器 URL(80/443 回调)，本工作台不做被动接收。
2. 三种可用通道：
   - kf 客服消息：用户 48 小时内与公众号有过互动即可下发文本，接口 message/custom/send；
   - template 服务号模板消息：不受 48 小时限制，但需已认证服务号且模板通过审核；
   - subscribe 一次性订阅消息：用户每授权一次可下发一条，无需关注，接口 message/template/subscribe。
3. 零资质联调：使用微信公众平台「测试号」(mp.weixin.qq.com/debug/cgi-bin/sandbox) 的
   appID/appsecret 与测试 openid 即可全程模拟发送，sandbox=True 时走同一套官方接口。
所有凭据经 Fernet 加密存于本地 config；未启用时消息只进本地 outbox，零外发。"""
from __future__ import annotations
import hashlib
import json
import time
import urllib.parse
import urllib.request

from .config import load_config
from .security import SECRETS
from . import db

WX_BASE = "https://api.weixin.qq.com/cgi-bin"


def status() -> dict:
    cfg = load_config()["wechat"]
    mode = cfg.get("send_mode", "kf")
    mode_note = {
        "kf": "客服消息：粉丝48小时内互动过即可下发，无需模板审核",
        "template": "服务号模板消息：不受48小时限制，需认证服务号+已审核模板ID",
        "subscribe": "一次性订阅消息：用户授权一次下发一条，无需关注",
    }.get(mode, "")
    return {"enabled": bool(cfg.get("enabled")), "configured": bool(cfg.get("appid")),
            "send_mode": mode, "sandbox": bool(cfg.get("sandbox")),
            "default_openid": cfg.get("default_openid", ""),
            "template_id": cfg.get("template_id", ""),
            "open_kfid": cfg.get("open_kfid", ""),
            "note": mode_note + "；本机仅出站调用API，无需公网服务器与回调。"}


def check_signature(token: str, timestamp: str, nonce: str, signature: str) -> bool:
    """微信服务器签名校验：sha1(sorted([token,timestamp,nonce]))（仅在将来需要被动接收时使用）。"""
    raw = "".join(sorted([token, timestamp, nonce]))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest() == signature


def _secret(cfg: dict) -> str:
    return SECRETS.decrypt(cfg.get("appsecret_enc", "")) or cfg.get("appsecret", "")


def access_token() -> str:
    """换取 access_token，缓存到本地 kv（微信有效期 7200 秒，提前 5 分钟过期）。"""
    cached = db.kv_get("wx_access_token", {})
    now = int(time.time())
    if cached and cached.get("expire_at", 0) - 300 > now and cached.get("appid"):
        cfg = load_config()["wechat"]
        if cached["appid"] == cfg.get("appid"):
            return cached["token"]
    cfg = load_config()["wechat"]
    if not cfg.get("enabled"):
        raise RuntimeError("微信通道未启用")
    if not cfg.get("appid") or not _secret(cfg):
        raise RuntimeError("尚未配置 AppID/AppSecret")
    q = urllib.parse.urlencode({"grant_type": "client_credential",
                                "appid": cfg["appid"], "secret": _secret(cfg)})
    with urllib.request.urlopen(f"{WX_BASE}/token?{q}", timeout=10) as r:
        data = json.loads(r.read().decode("utf-8"))
    if "access_token" not in data:
        raise RuntimeError(f"获取 access_token 失败：errcode={data.get('errcode')} {data.get('errmsg')}")
    db.kv_set("wx_access_token", {"appid": cfg["appid"], "token": data["access_token"],
                                  "expire_at": now + int(data.get("expires_in", 7200))})
    return data["access_token"]


def _post(api_path: str, payload: dict) -> dict:
    token = access_token()
    req = urllib.request.Request(
        f"{WX_BASE}/{api_path}?access_token={token}",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def _wrap_fields(content: str) -> dict:
    """把纯文本提醒包装成模板 data 字段（first/tail 通用约定，可按审核模板字段调整）。"""
    return {"first": {"value": "办案提醒", "color": "#7c5cbf"},
            "keyword1": {"value": time.strftime("%Y-%m-%d %H:%M")},
            "keyword2": {"value": content[:180]},
            "remark": {"value": "来自律师本地工作台（本地生成，出站仅本条消息）"}}


def send_text(openid: str, content: str, mode: str | None = None) -> dict:
    """按配置通道立即发送一条提醒，返回微信响应。"""
    cfg = load_config()["wechat"]
    if not cfg.get("enabled"):
        return {"ok": False, "error": "微信通道未启用"}
    if not openid:
        return {"ok": False, "error": "缺少接收人 openid（测试号可在沙盒页获得关注者 openid）"}
    mode = mode or cfg.get("send_mode", "kf")
    if mode == "kf":
        resp = _post("message/custom/send",
                     {"touser": openid, "msgtype": "text", "text": {"content": content}})
    elif mode == "template":
        tpl = cfg.get("template_id", "")
        if not tpl:
            return {"ok": False, "error": "模板消息需先在设置中填写已审核 template_id"}
        resp = _post("message/template/send",
                     {"touser": openid, "template_id": tpl,
                      "url": "", "data": _wrap_fields(content)})
    elif mode == "subscribe":
        tpl = cfg.get("template_id", "")
        if not tpl:
            return {"ok": False, "error": "一次性订阅消息需填写订阅模板 template_id"}
        resp = _post("message/template/subscribe",
                     {"touser": openid, "template_id": tpl, "url": "",
                      "scene": 1000, "title": "办案提醒", "data": _wrap_fields(content)})
    else:
        return {"ok": False, "error": f"未知发送模式：{mode}"}
    ok = resp.get("errcode") == 0
    return {"ok": ok, "resp": resp, "mode": mode}


def enqueue(target_openid: str, content: str) -> dict:
    """把提醒放入本地发送队列（未启用微信时仅留存本地提醒中心）。"""
    cfg = load_config()["wechat"]
    channel = "wechat" if cfg.get("enabled") else "local"
    target = target_openid or cfg.get("default_openid", "")
    db.execute("INSERT INTO outbox(channel,target,content,status,created) VALUES(?,?,?,?,?)",
               (channel, target, content, "待发送", db.now()))
    return {"queued": True, "channel": channel}


def send_one(outbox_id: int) -> dict:
    row = db.query_one("SELECT * FROM outbox WHERE id=?", (outbox_id,))
    if not row:
        return {"ok": False, "error": "队列无此消息"}
    cfg = load_config()["wechat"]
    if not cfg.get("enabled"):
        return {"ok": False, "error": "微信通道未启用，消息保留在本地提醒中心"}
    res = send_text(row["target"] or cfg.get("default_openid", ""),
                    row["content"], cfg.get("send_mode", "kf"))
    if res.get("ok"):
        db.execute("UPDATE outbox SET status=?, sent=?, resp=? WHERE id=?",
                   ("已发送", db.now(), json.dumps(res["resp"], ensure_ascii=False), outbox_id))
    else:
        db.execute("UPDATE outbox SET status=?, resp=? WHERE id=?",
                   ("失败", res.get("error") or json.dumps(res.get("resp", {}), ensure_ascii=False),
                    outbox_id))
    return res


def flush_due_reminders() -> int:
    """把到期的期限提醒自动入队（由主程序定时调用）。"""
    n = 0
    today = time.strftime("%Y-%m-%d")
    rows = db.query("SELECT * FROM reminders WHERE done=0 AND kind='期限' AND due<=?", (today,))
    cfg = load_config()["wechat"]
    for r in rows:
        db.execute("INSERT INTO outbox(channel,target,content,status,created) VALUES(?,?,?,?,?)",
                   ("wechat" if cfg.get("enabled") else "local",
                    cfg.get("default_openid", ""),
                    f"【办案提醒】{r['title']}，截止/节点日期：{r['due']}。{r['detail']}",
                    "待发送", db.now()))
        n += 1
    return n
