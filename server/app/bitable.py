# -*- coding: utf-8 -*-
"""飞书多维表格同步。

把本地「档案总表 / 案件表 / 客户表 / 创收表 / 提醒表」以飞书式多维表格的形态
一键同步到飞书多维表格（Bitable）。未配置凭据时只生成本地预览与 CSV 导出，零外发。

飞书开放平台接口（已按官方文档实现）：
- 创建多维表格  POST /open-apis/bitable/v1/apps
- 创建数据表    POST /open-apis/bitable/v1/apps/{app_token}/tables
- 列出记录      GET  /open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records
- 批量删除      POST /open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_delete
- 批量新增      POST /open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_create
"""
from __future__ import annotations
import csv
import io
import json
import urllib.request
import urllib.error
from datetime import datetime

from .config import DATA_DIR, EXPORT_DIR, load_config, save_config
from .security import SECRETS
from . import db

API = "https://open.feishu.cn/open-apis/bitable/v1"


def _cfg() -> dict:
    return load_config().get("bitable", {}) or {}


def _feishu_cfg() -> dict:
    return load_config().get("feishu", {}) or {}


def _secret() -> str:
    cfg = _feishu_cfg()
    return SECRETS.decrypt(cfg.get("app_secret_enc", "")) or cfg.get("app_secret", "")


def _http(method: str, path: str, payload: dict | None = None,
          token: str | None = None, timeout: float = 20.0) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(API + path, data=data, method=method)
    req.add_header("Content-Type", "application/json; charset=utf-8")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def tenant_token() -> str:
    cfg = _feishu_cfg()
    if not cfg.get("enabled") or not cfg.get("app_id"):
        raise RuntimeError("飞书接口未启用或未配置 App ID")
    secret = _secret()
    if not secret:
        raise RuntimeError("未配置 App Secret（将加密保存在本地）")
    r = _http("POST", "/../auth/v3/tenant_access_token/internal",
              {"app_id": cfg["app_id"], "app_secret": secret}) \
        if False else None
    req = urllib.request.Request(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        data=json.dumps({"app_id": cfg["app_id"], "app_secret": secret}).encode("utf-8"),
        method="POST")
    req.add_header("Content-Type", "application/json; charset=utf-8")
    with urllib.request.urlopen(req, timeout=15) as resp:
        r = json.loads(resp.read().decode("utf-8"))
    if r.get("code") != 0:
        raise RuntimeError(f"获取 tenant_access_token 失败：{r}")
    return r["tenant_access_token"]


# ---------------- 数据集定义（本地多维表格） ----------------
def _fmt_ts(v) -> str:
    try:
        return datetime.fromtimestamp(float(v)).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ""


def _size(v) -> str:
    try:
        n = float(v or 0)
    except (TypeError, ValueError):
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return ""


DATASETS: dict[str, dict] = {
    "archive": {
        "name": "档案总表",
        "fields": [("标题", "text"), ("分类", "text"), ("客户", "text"), ("关联案件", "text"),
                   ("类型", "text"), ("大小", "text"), ("修改时间", "text"),
                   ("打开次数", "number"), ("最近打开", "text"), ("标签", "text"),
                   ("备注", "text"), ("本地路径", "text")],
        "rows": lambda: [
            {"标题": r["title"] or "", "分类": r["category"] or "", "客户": r["client"] or "",
             "关联案件": r["case_ref"] or "", "类型": (r["ext"] or "").lstrip("."),
             "大小": _size(r["size"]), "修改时间": _fmt_ts(r["mtime"]),
             "打开次数": r["open_count"] or 0, "最近打开": r["last_open"] or "",
             "标签": r["tags"] or "", "备注": r["remark"] or "", "本地路径": r["rel_path"] or ""}
            for r in db.query("SELECT * FROM doc_registry ORDER BY updated DESC, last_open DESC")
        ],
    },
    "cases": {
        "name": "案件表",
        "fields": [("案件名称", "text"), ("案件类型", "text"), ("业务类别", "text"),
                   ("客户", "text"), ("对方当事人", "text"), ("管辖机构", "text"),
                   ("当前阶段", "text"), ("案号/编号", "text"), ("律师费", "number"),
                   ("已收款", "number"), ("待回款", "number"), ("标的额", "number"),
                   ("风险等级", "text"), ("优先级", "text"), ("委托日期", "text"),
                   ("最近节点", "text"), ("逾期数", "number"), ("标签", "text")],
        "rows": lambda: _case_rows(),
    },
    "clients": {
        "name": "客户表",
        "fields": [("客户名称", "text"), ("联系方式", "text"), ("证件号码", "text"),
                   ("对方当事人", "text"), ("关联案件数", "number"), ("累计创收", "number"),
                   ("最近联系", "text"), ("本地路径", "text")],
        "rows": lambda: _client_rows(),
    },
    "revenue": {
        "name": "创收表",
        "fields": [("日期", "text"), ("类型", "text"), ("客户", "text"), ("项目/案件", "text"),
                   ("金额", "number"), ("收付方式", "text"), ("发票号", "text"),
                   ("已开票", "text"), ("备注", "text")],
        "rows": lambda: [
            {"日期": r["fee_date"] or "", "类型": r["record_type"] or "",
             "客户": r["client"] or "", "项目/案件": r["title"] or "",
             "金额": r["amount"] or 0, "收付方式": r["method"] or "",
             "发票号": r["invoice_no"] or "", "已开票": "是" if r["invoiced"] else "否",
             "备注": r["note"] or ""}
            for r in db.query("SELECT * FROM fee_records ORDER BY fee_date DESC, id DESC")
        ],
    },
    "reminders": {
        "name": "提醒表",
        "fields": [("类别", "text"), ("事项", "text"), ("说明", "text"),
                   ("节点日期", "text"), ("级别", "text"), ("状态", "text")],
        "rows": lambda: [
            {"类别": r["kind"] or "", "事项": r["title"] or "", "说明": (r["detail"] or "")[:300],
             "节点日期": r["due"] or "", "级别": r["level"] or "",
             "状态": "已完成" if r["done"] else "待处理"}
            for r in db.query("SELECT * FROM reminders ORDER BY due ASC, level DESC")
        ],
    },
}


def _case_rows() -> list[dict]:
    from . import workflow
    rows = []
    for c in db.query("SELECT * FROM cases ORDER BY updated DESC"):
        tl = workflow.timeline_for(c)
        overdue = [t for t in tl if "逾期" in (t.get("status") or "")]
        next_due = next((t["due"] for t in tl if t.get("due") and
                         not (t.get("status") or "").startswith(("已完成", "未触发"))), "")
        fee = float(c.get("fee_amount") or 0)
        paid = float(c.get("fee_paid") or 0)
        rows.append({
            "案件名称": f"{c.get('client','')}-{c.get('cause','')}",
            "案件类型": c.get("case_type") or "", "业务类别": c.get("case_category") or "",
            "客户": c.get("client") or "", "对方当事人": c.get("opponent") or "",
            "管辖机构": c.get("court") or "", "当前阶段": c.get("stage") or "",
            "案号/编号": c.get("case_no") or "", "律师费": fee, "已收款": paid,
            "待回款": round(max(fee - paid, 0), 2), "标的额": float(c.get("subject_amount") or 0),
            "风险等级": c.get("risk_level") or "中", "优先级": c.get("priority") or "普通",
            "委托日期": c.get("contact_date") or "", "最近节点": next_due,
            "逾期数": len(overdue), "标签": c.get("tags") or "",
        })
    return rows


def _client_rows() -> list[dict]:
    out = []
    for f in db.query("SELECT rel_path,title,frontmatter FROM files WHERE ftype='client' ORDER BY title"):
        try:
            fm = json.loads(f["frontmatter"] or "{}")
        except Exception:
            fm = {}
        name = f["title"] or ""
        case_cnt = db.query_one("SELECT COUNT(*) c FROM cases WHERE client=?", (name,))["c"]
        amount = db.query_one("SELECT COALESCE(SUM(amount),0) s FROM fee_records WHERE client=?",
                              (name,))["s"] or 0
        out.append({"客户名称": name, "联系方式": fm.get("联系方式", ""),
                    "证件号码": fm.get("身份证/统一信用代码", ""),
                    "对方当事人": fm.get("对方当事人", ""),
                    "关联案件数": case_cnt, "累计创收": round(amount, 2),
                    "最近联系": fm.get("最近联系", ""), "本地路径": f["rel_path"]})
    return out


# ---------------- 本地表格读取 ----------------
def table(dataset: str) -> dict:
    spec = DATASETS.get(dataset)
    if not spec:
        raise ValueError(f"未知数据集：{dataset}")
    rows = spec["rows"]()
    return {"key": dataset, "name": spec["name"],
            "fields": [{"name": n, "type": t} for n, t in spec["fields"]],
            "rows": rows, "count": len(rows)}


def preview(dataset: str) -> dict:
    return table(dataset)


def export_csv(dataset: str) -> dict:
    t = table(dataset)
    buf = io.StringIO()
    names = [f["name"] for f in t["fields"]]
    w = csv.DictWriter(buf, fieldnames=names)
    w.writeheader()
    for r in t["rows"]:
        w.writerow({k: r.get(k, "") for k in names})
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = EXPORT_DIR / f"{t['name']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    path.write_text(buf.getvalue(), encoding="utf-8-sig")
    db.audit("导出多维表格CSV", str(path))
    return {"ok": True, "path": str(path), "name": path.name, "rows": t["count"]}


# ---------------- 一键同步到飞书 ----------------
def status() -> dict:
    cfg, fs = _cfg(), _feishu_cfg()
    return {"configured": bool(fs.get("app_id")) and bool(_secret()),
            "enabled": bool(fs.get("enabled")),
            "app_token": cfg.get("app_token", ""),
            "table_ids": cfg.get("table_ids", {}),
            "last_sync": db.kv_get("bitable_last_sync", ""),
            "datasets": [{"key": k, "name": v["name"], "count": len(v["rows"]())}
                         for k, v in DATASETS.items()]}


def save_settings(patch: dict) -> dict:
    cfg = load_config()
    bt = cfg.setdefault("bitable", {})
    for k in ("app_token", "table_ids"):
        if k in patch:
            bt[k] = patch[k]
    save_config(cfg)
    return status()


_FIELD_TYPE = {"text": 1, "number": 2, "date": 5}


def _ensure_app(token: str, cfg: dict) -> str:
    app_token = (_cfg().get("app_token") or "").strip()
    if app_token:
        return app_token
    folder = _feishu_cfg().get("folder_token", "")
    payload = {"name": "律师工作台·档案总表"}
    if folder:
        payload["folder_token"] = folder
    r = _http("POST", "/apps", payload, token)
    if r.get("code") != 0:
        raise RuntimeError(f"创建多维表格失败：{r.get('msg')}（{r.get('code')}）")
    app_token = r["data"]["app"]["app_token"]
    cfg["app_token"] = app_token
    return app_token


def _ensure_table(token: str, app_token: str, dataset: str, spec: dict, cfg: dict) -> str:
    ids = cfg.get("table_ids") or {}
    tid = ids.get(dataset)
    if tid:
        return tid
    r = _http("POST", f"/apps/{app_token}/tables", {
        "table": {"name": spec["name"], "default_view_name": "全部",
                  "fields": [{"field_name": n,
                              "type": _FIELD_TYPE.get(t, 1)} for n, t in spec["fields"]]}
    }, token)
    if r.get("code") != 0:
        raise RuntimeError(f"创建数据表失败：{r.get('msg')}（{r.get('code')}）")
    tid = r["data"]["table_id"]
    ids[dataset] = tid
    cfg["table_ids"] = ids
    return tid


def _clear_records(token: str, app_token: str, table_id: str) -> int:
    ids, page_token, n = [], None, 0
    while True:
        path = f"/apps/{app_token}/tables/{table_id}/records?page_size=500"
        if page_token:
            path += f"&page_token={page_token}"
        r = _http("GET", path, None, token)
        if r.get("code") != 0:
            break
        items = (r.get("data") or {}).get("items", [])
        ids += [i["record_id"] for i in items]
        page_token = (r.get("data") or {}).get("page_token")
        if not (r.get("data") or {}).get("has_more"):
            break
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        _http("POST", f"/apps/{app_token}/tables/{table_id}/records/batch_delete",
              {"records": chunk}, token)
        n += len(chunk)
    return n


def sync(dataset: str, clear: bool = True) -> dict:
    """一键把本地表格同步到飞书多维表格。未配置时给出明确降级提示，零外发。"""
    spec = DATASETS.get(dataset)
    if not spec:
        raise ValueError(f"未知数据集：{dataset}")
    rows = spec["rows"]()
    if not rows:
        return {"ok": False, "error": "本地暂无数据可同步"}

    fs = _feishu_cfg()
    if not fs.get("enabled") or not fs.get("app_id") or not _secret():
        return {"ok": False, "error": "飞书接口未启用或未配置凭据，已保留在本地（零外发）。"
                                      "可先使用「导出 CSV」获取表格文件。",
                "fallback": "csv", "count": len(rows)}

    cfg_all = load_config()
    bt_cfg = cfg_all.setdefault("bitable", {})
    try:
        token = tenant_token()
        app_token = _ensure_app(token, bt_cfg)
        table_id = _ensure_table(token, app_token, dataset, spec, bt_cfg)
        save_config(cfg_all)

        cleared = _clear_records(token, app_token, table_id) if clear else 0
        created = 0
        for i in range(0, len(rows), 500):
            chunk = rows[i:i + 500]
            r = _http("POST", f"/apps/{app_token}/tables/{table_id}/records/batch_create",
                      {"records": [{"fields": row} for row in chunk]}, token)
            if r.get("code") != 0:
                return {"ok": False, "error": f"写入记录失败：{r.get('msg')}（{r.get('code')}）",
                        "written": created}
            created += len(chunk)
        db.kv_set("bitable_last_sync", db.now())
        db.kv_set("bitable_app_token", app_token)
        db.audit("同步飞书多维表格", f"{spec['name']}：{created} 行")
        return {"ok": True, "dataset": dataset, "name": spec["name"], "written": created,
                "cleared": cleared, "app_token": app_token, "table_id": table_id,
                "url": f"https://feishu.cn/base/{app_token}"}
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": f"飞书接口 HTTP 错误：{e.code} {e.reason}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
