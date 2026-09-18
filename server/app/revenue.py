# -*- coding: utf-8 -*-
"""创收管理：律师费 / 其他收入 / 成本支出。

数据全部落在本地 SQLite，支持按案件、客户、月份、类型多维统计与回款进度跟踪。
律师费可在「新建案件」流程中前置录入，也可在本模块单独登记或补录。
"""
from __future__ import annotations
from datetime import datetime

from . import db

INCOME_TYPES = ("律师费", "其他收入")
COST_TYPES = ("成本支出",)
ALL_TYPES = INCOME_TYPES + COST_TYPES

METHODS = ["银行转账", "现金", "微信", "支付宝", "支票", "承兑汇票", "其他"]


def _num(v, default=0.0) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return default


def list_records(rtype: str = "", year: str = "", client: str = "",
                 case_path: str = "", keyword: str = "", limit: int = 500) -> list[dict]:
    sql = "SELECT * FROM fee_records WHERE 1=1"
    args: list = []
    if rtype:
        sql += " AND record_type=?"; args.append(rtype)
    if year:
        sql += " AND substr(fee_date,1,4)=?"; args.append(str(year))
    if client:
        sql += " AND client LIKE ?"; args.append(f"%{client}%")
    if case_path:
        sql += " AND case_path=?"; args.append(case_path)
    if keyword:
        sql += " AND (title LIKE ? OR note LIKE ? OR invoice_no LIKE ?)"
        args += [f"%{keyword}%"] * 3
    sql += " ORDER BY fee_date DESC, id DESC LIMIT ?"
    args.append(limit)
    return db.query(sql, tuple(args))


def get_record(rid: int) -> dict:
    row = db.query_one("SELECT * FROM fee_records WHERE id=?", (rid,))
    if not row:
        raise ValueError("记录不存在")
    return row


def add_record(data: dict) -> dict:
    rtype = (data.get("record_type") or "律师费").strip()
    if rtype not in ALL_TYPES:
        raise ValueError(f"类型必须是：{'/'.join(ALL_TYPES)}")
    amount = _num(data.get("amount"))
    row = {
        "record_type": rtype,
        "case_path": (data.get("case_path") or "").strip(),
        "client": (data.get("client") or "").strip(),
        "title": (data.get("title") or ("律师费" if rtype == "律师费" else rtype)).strip(),
        "amount": amount,
        "fee_date": (data.get("fee_date") or db.today()).strip(),
        "method": (data.get("method") or "银行转账").strip(),
        "invoice_no": (data.get("invoice_no") or "").strip(),
        "invoiced": 1 if data.get("invoiced") else 0,
        "note": (data.get("note") or "").strip(),
        "created": db.now(),
    }
    rid = db.insert("fee_records", row)
    _sync_case_fee(row["case_path"])
    db.audit("新增创收记录", f"{rtype} {amount} {row['client']}")
    return get_record(rid)


def update_record(rid: int, patch: dict) -> dict:
    row = get_record(rid)
    fields = ("record_type", "case_path", "client", "title", "amount",
              "fee_date", "method", "invoice_no", "invoiced", "note")
    sets, args = [], []
    for f in fields:
        if f in patch:
            val = patch[f]
            if f == "amount":
                val = _num(val)
            elif f == "invoiced":
                val = 1 if val else 0
            elif isinstance(val, str):
                val = val.strip()
            sets.append(f"{f}=?"); args.append(val)
    if not sets:
        return row
    args.append(rid)
    db.execute(f"UPDATE fee_records SET {','.join(sets)} WHERE id=?", tuple(args))
    _sync_case_fee(row["case_path"])
    new = get_record(rid)
    if new["case_path"] != row["case_path"]:
        _sync_case_fee(new["case_path"])
    return new


def delete_record(rid: int) -> dict:
    row = get_record(rid)
    db.execute("DELETE FROM fee_records WHERE id=?", (rid,))
    _sync_case_fee(row["case_path"])
    db.audit("删除创收记录", str(rid))
    return {"ok": True}


def _sync_case_fee(case_path: str):
    """把该案件已收律师费回写到 cases 表，供首页与案件列表展示回款进度。"""
    if not case_path:
        return
    row = db.query_one("SELECT COALESCE(SUM(amount),0) s FROM fee_records "
                       "WHERE case_path=? AND record_type='律师费'", (case_path,))
    paid = row["s"] if row else 0
    db.execute("UPDATE cases SET fee_paid=? WHERE rel_path=?", (paid, case_path))


def sync_all_case_fees() -> int:
    n = 0
    for c in db.query("SELECT rel_path FROM cases"):
        _sync_case_fee(c["rel_path"]); n += 1
    return n


def summary(year: str = "") -> dict:
    """核心汇总卡片数据。"""
    where, args = "", []
    if year:
        where = " WHERE substr(fee_date,1,4)=?"
        args.append(str(year))
    rows = db.query(f"SELECT record_type, COALESCE(SUM(amount),0) s, COUNT(*) c "
                    f"FROM fee_records{where} GROUP BY record_type", tuple(args))
    agg = {r["record_type"]: r for r in rows}
    fee = agg.get("律师费", {}).get("s", 0) or 0
    other = agg.get("其他收入", {}).get("s", 0) or 0
    cost = agg.get("成本支出", {}).get("s", 0) or 0
    income = fee + other
    invoiced = db.query_one(
        f"SELECT COALESCE(SUM(amount),0) s FROM fee_records"
        f"{where + (' AND' if where else ' WHERE')} invoiced=1", tuple(args))["s"] or 0
    receivable = db.query_one(
        "SELECT COALESCE(SUM(MAX(amount-fee_paid,0)),0) s FROM "
        "(SELECT rel_path, MAX(fee_amount) amount, MAX(fee_paid) fee_paid FROM cases "
        " WHERE fee_amount>0 GROUP BY rel_path)")["s"] or 0
    return {
        "year": year or "全部",
        "律师费": round(fee, 2), "其他收入": round(other, 2),
        "成本支出": round(cost, 2),
        "总收入": round(income, 2), "净收益": round(income - cost, 2),
        "已开票金额": round(invoiced, 2),
        "未回款金额": round(receivable, 2),
        "记录数": sum(r["c"] for r in rows),
    }


def monthly(year: str = "") -> list[dict]:
    where, args = "", []
    if year:
        where = " WHERE substr(fee_date,1,4)=?"
        args.append(str(year))
    rows = db.query(
        f"SELECT substr(fee_date,1,7) ym, record_type, COALESCE(SUM(amount),0) s "
        f"FROM fee_records{where} GROUP BY ym, record_type ORDER BY ym", tuple(args))
    bucket: dict[str, dict] = {}
    for r in rows:
        b = bucket.setdefault(r["ym"] or "未填日期",
                              {"ym": r["ym"] or "未填日期", "律师费": 0.0,
                               "其他收入": 0.0, "成本支出": 0.0})
        b[r["record_type"]] = round(r["s"], 2)
    out = sorted(bucket.values(), key=lambda x: x["ym"])
    for b in out:
        b["收入合计"] = round(b["律师费"] + b["其他收入"], 2)
        b["净收益"] = round(b["收入合计"] - b["成本支出"], 2)
    return out


def by_dimension(dim: str, year: str = "", top: int = 10) -> list[dict]:
    """按客户 / 案件 / 类型维度聚合收入。"""
    if dim == "client":
        col, label = "client", "客户"
    elif dim == "case":
        col, label = "case_path", "案件"
    else:
        col, label = "record_type", "类型"
    where, args = " WHERE record_type IN ('律师费','其他收入')", []
    if year:
        where += " AND substr(fee_date,1,4)=?"; args.append(str(year))
    rows = db.query(
        f"SELECT {col} k, COALESCE(SUM(amount),0) s, COUNT(*) c FROM fee_records"
        f"{where} GROUP BY {col} ORDER BY s DESC LIMIT ?", tuple(args + [top]))
    total = sum(r["s"] for r in rows) or 1
    return [{"key": r["k"] or "未指定", "label": label, "amount": round(r["s"], 2),
             "count": r["c"], "pct": round(r["s"] / total * 100, 1)} for r in rows]


def years() -> list[str]:
    rows = db.query("SELECT DISTINCT substr(fee_date,1,4) y FROM fee_records "
                    "WHERE fee_date IS NOT NULL AND fee_date!='' ORDER BY y DESC")
    ys = [r["y"] for r in rows if r["y"]]
    cur = datetime.now().strftime("%Y")
    if cur not in ys:
        ys.insert(0, cur)
    return ys


def methods() -> list[str]:
    return METHODS


def types() -> list[str]:
    return list(ALL_TYPES)


def case_fee(case_path: str) -> dict:
    rows = db.query("SELECT * FROM fee_records WHERE case_path=? ORDER BY fee_date DESC",
                    (case_path,))
    c = db.query_one("SELECT * FROM cases WHERE rel_path=?", (case_path,)) or {}
    fee_amount = _num(c.get("fee_amount"))
    paid = sum(r["amount"] or 0 for r in rows if r["record_type"] == "律师费")
    return {
        "case_path": case_path,
        "contract_amount": fee_amount,
        "received": round(paid, 2),
        "outstanding": round(max(fee_amount - paid, 0), 2),
        "progress": round(paid / fee_amount * 100, 1) if fee_amount else 0,
        "records": rows,
    }
