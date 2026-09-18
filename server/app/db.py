# -*- coding: utf-8 -*-
"""本地 SQLite 索引库。

设计原则：SQLite 只保存索引、状态与结构化业务数据；笔记正文永远以本地 Markdown 文件为准，
生成的文书以本地 Word/PDF 原件为准，删库可从本地文件完整重建索引。
"""
from __future__ import annotations
import json
import sqlite3
import threading
from datetime import datetime
from typing import Any, Optional

from .config import DB_PATH

_LOCK = threading.RLock()


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


CONN = get_conn()

# ---------------- 表结构 ----------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS files(
    rel_path TEXT PRIMARY KEY, title TEXT, ftype TEXT,
    mtime REAL, size INTEGER, sha256 TEXT,
    frontmatter TEXT, body TEXT, updated TEXT);
CREATE TABLE IF NOT EXISTS links(src TEXT, dst TEXT, anchor TEXT);
CREATE INDEX IF NOT EXISTS idx_links_dst ON links(dst);

CREATE TABLE IF NOT EXISTS cases(
    rel_path TEXT PRIMARY KEY,
    client TEXT, client_path TEXT, cause TEXT, court TEXT,
    procedure TEXT, stage TEXT, case_no TEXT,
    filing_date TEXT, hearing_date TEXT, judgment_date TEXT,
    judgment_eff_date TEXT, updated TEXT);
CREATE INDEX IF NOT EXISTS idx_cases_client ON cases(client);

CREATE TABLE IF NOT EXISTS gen_docs(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_path TEXT, seq INTEGER, doc_type TEXT,
    filename TEXT, rel_path TEXT, created TEXT,
    system_hash TEXT, disk_hash TEXT, sync_state TEXT DEFAULT '一致');

CREATE TABLE IF NOT EXISTS reminders(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT, title TEXT, detail TEXT, due TEXT,
    level TEXT DEFAULT '普通', done INTEGER DEFAULT 0,
    ref TEXT, created TEXT);
CREATE INDEX IF NOT EXISTS idx_rem_due ON reminders(due);

CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT);

CREATE TABLE IF NOT EXISTS outbox(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel TEXT, target TEXT, content TEXT,
    status TEXT DEFAULT '待发送', created TEXT, sent TEXT, resp TEXT);

-- 案件类型（内置诉讼/非诉 + 用户自定义）
CREATE TABLE IF NOT EXISTS case_types(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE, category TEXT, flow TEXT,
    builtin INTEGER DEFAULT 0, enabled INTEGER DEFAULT 1,
    sort INTEGER DEFAULT 0, created TEXT);

-- 创收管理：律师费 / 其他收入 / 成本支出
CREATE TABLE IF NOT EXISTS fee_records(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    record_type TEXT, case_path TEXT, client TEXT, title TEXT,
    amount REAL DEFAULT 0, fee_date TEXT, method TEXT,
    invoice_no TEXT, invoiced INTEGER DEFAULT 0, note TEXT, created TEXT);
CREATE INDEX IF NOT EXISTS idx_fee_type ON fee_records(record_type);
CREATE INDEX IF NOT EXISTS idx_fee_date ON fee_records(fee_date);

-- 发票管理（邮箱自动收取 + 手工登记）
CREATE TABLE IF NOT EXISTS invoices(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_name TEXT, file_path TEXT UNIQUE, rel_path TEXT,
    sender TEXT, subject TEXT, amount REAL,
    invoice_date TEXT, received_at TEXT, source TEXT,
    month_dir TEXT, sha256 TEXT, ext TEXT,
    notified INTEGER DEFAULT 0, note TEXT, created TEXT);
CREATE INDEX IF NOT EXISTS idx_inv_date ON invoices(invoice_date);

-- 档案库总表（飞书式多维表格数据源）
CREATE TABLE IF NOT EXISTS doc_registry(
    rel_path TEXT PRIMARY KEY,
    title TEXT, category TEXT, ext TEXT,
    size INTEGER, mtime REAL,
    client TEXT, case_ref TEXT, tags TEXT,
    starred INTEGER DEFAULT 0, remark TEXT,
    open_count INTEGER DEFAULT 0, last_open TEXT,
    created TEXT, updated TEXT);
CREATE INDEX IF NOT EXISTS idx_doc_cat ON doc_registry(category);
CREATE INDEX IF NOT EXISTS idx_doc_open ON doc_registry(last_open);

-- AI 会话与消息
CREATE TABLE IF NOT EXISTS ai_sessions(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT, model TEXT, mode TEXT, system_prompt TEXT,
    created TEXT, updated TEXT);
CREATE TABLE IF NOT EXISTS ai_messages(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER, role TEXT, content TEXT,
    evidence TEXT, model TEXT, mode TEXT, created TEXT);
CREATE INDEX IF NOT EXISTS idx_msg_sess ON ai_messages(session_id);

-- 日程 / 待办
CREATE TABLE IF NOT EXISTS tasks(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT, detail TEXT, due TEXT, level TEXT DEFAULT '普通',
    kind TEXT DEFAULT '待办', case_path TEXT,
    done INTEGER DEFAULT 0, remind TEXT DEFAULT '', email TEXT DEFAULT '',
    reminded INTEGER DEFAULT 0, created TEXT);
CREATE INDEX IF NOT EXISTS idx_task_due ON tasks(due);

-- 计时工时
CREATE TABLE IF NOT EXISTS time_entries(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_path TEXT, title TEXT, started TEXT, ended TEXT,
    seconds INTEGER DEFAULT 0, billable INTEGER DEFAULT 1,
    rate REAL DEFAULT 0, note TEXT, created TEXT);

-- 通讯录（客户联系人 / 法官 / 书记员 / 对方律师 / 其他）
CREATE TABLE IF NOT EXISTS contacts(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT, role TEXT, org TEXT, phone TEXT,
    email TEXT, address TEXT, note TEXT, case_path TEXT, created TEXT);

-- 模板文书库（起诉状/答辩状示范文本 + 诉讼保全模板；文件存放 data/templates/）
CREATE TABLE IF NOT EXISTS doc_templates(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rel_path TEXT UNIQUE,       -- 相对 data/templates/
    grp TEXT, category TEXT,    -- 组：起诉状答辩状/诉讼保全；分类：八大类
    name TEXT, cause TEXT,      -- 显示名 / 案由
    kind TEXT, is_example INTEGER DEFAULT 0,
    title TEXT, updated TEXT);
CREATE INDEX IF NOT EXISTS idx_tpl_grp ON doc_templates(grp);
CREATE INDEX IF NOT EXISTS idx_tpl_cause ON doc_templates(cause);

-- 接案笔录（v0.9.8）：录音转写、角色区分、要素提取、Word 笔录
CREATE TABLE IF NOT EXISTS intake_records(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created TEXT NOT NULL,          -- 建档时间
    started_at TEXT DEFAULT '',     -- 录音开始时间
    ended_at TEXT DEFAULT '',       -- 录音结束时间
    client TEXT DEFAULT '',         -- 当事人/客户
    lawyer TEXT DEFAULT '',         -- 接待律师
    recorder TEXT DEFAULT '',       -- 记录人
    location TEXT DEFAULT '',       -- 接待地点
    duration REAL DEFAULT 0,        -- 录音秒数
    audio_path TEXT DEFAULT '',     -- 相对 VAULT
    transcript_path TEXT DEFAULT '',
    docx_path TEXT DEFAULT '',
    status TEXT DEFAULT 'transcribed', -- transcribed/done
    summary TEXT DEFAULT '',
    turns_json TEXT DEFAULT '[]',
    meta_json TEXT DEFAULT '{}');
"""

# 旧库升级：cases 表新增列（SQLite 不支持 IF NOT EXISTS for ADD COLUMN）
CASE_EXTRA_COLUMNS = {
    "case_type": "TEXT DEFAULT ''",
    "case_category": "TEXT DEFAULT ''",
    "fee_amount": "REAL DEFAULT 0",
    "fee_method": "TEXT DEFAULT ''",
    "fee_paid": "REAL DEFAULT 0",
    "subject_amount": "REAL DEFAULT 0",
    "risk_level": "TEXT DEFAULT '中'",
    "close_date": "TEXT DEFAULT ''",
    "priority": "TEXT DEFAULT '普通'",
    "opponent": "TEXT DEFAULT ''",
    "progress": "INTEGER DEFAULT 0",
    "tags": "TEXT DEFAULT ''",
    "contact_date": "TEXT DEFAULT ''",
    "judgment_type": "TEXT DEFAULT '判决'",
}


def _migrate_cases():
    cols = {r["name"] for r in query("PRAGMA table_info(cases)")}
    for col, ddl in CASE_EXTRA_COLUMNS.items():
        if col not in cols:
            try:
                execute(f"ALTER TABLE cases ADD COLUMN {col} {ddl}")
            except Exception:
                pass


TASK_EXTRA_COLUMNS = {
    "remind": "TEXT DEFAULT ''",
    "email": "TEXT DEFAULT ''",
    "reminded": "INTEGER DEFAULT 0",
}


def _migrate_tasks():
    cols = {r["name"] for r in query("PRAGMA table_info(tasks)")}
    for col, ddl in TASK_EXTRA_COLUMNS.items():
        if col not in cols:
            try:
                execute(f"ALTER TABLE tasks ADD COLUMN {col} {ddl}")
            except Exception:
                pass


# gen_docs 扩展列：记录由模板生成的文书来源模板，便于追溯
GEN_DOCS_EXTRA_COLUMNS = {
    "template_id": "INTEGER DEFAULT 0",
}


def _migrate_gen_docs():
    cols = {r["name"] for r in query("PRAGMA table_info(gen_docs)")}
    for col, ddl in GEN_DOCS_EXTRA_COLUMNS.items():
        if col not in cols:
            try:
                execute(f"ALTER TABLE gen_docs ADD COLUMN {col} {ddl}")
            except Exception:
                pass


def init_db() -> None:
    with _LOCK, CONN:
        CONN.executescript(SCHEMA)
    _migrate_cases()
    _migrate_tasks()
    _migrate_gen_docs()
    _seed_case_types()
    _seed_nav_order()


# ---------------- 案件类型种子数据 ----------------
# 内置诉讼类（沿用民商事流程引擎）+ 非诉业务 + 用户可自行扩展
BUILTIN_CASE_TYPES = [
    # —— 诉讼/仲裁/执行（走民商事流程引擎）——
    ("劳动争议", "诉讼仲裁", "civil_flow", 1),
    ("合同纠纷", "诉讼仲裁", "civil_flow", 2),
    ("民间借贷", "诉讼仲裁", "civil_flow", 3),
    ("婚姻家庭", "诉讼仲裁", "civil_flow", 4),
    ("继承纠纷", "诉讼仲裁", "civil_flow", 5),
    ("侵权责任纠纷", "诉讼仲裁", "civil_flow", 6),
    ("房屋买卖/租赁", "诉讼仲裁", "civil_flow", 7),
    ("建设工程", "诉讼仲裁", "civil_flow", 8),
    ("公司股权纠纷", "诉讼仲裁", "civil_flow", 9),
    ("知识产权", "诉讼仲裁", "civil_flow", 10),
    ("买卖合同纠纷", "诉讼仲裁", "civil_flow", 11),
    ("金融借款", "诉讼仲裁", "civil_flow", 12),
    ("票据纠纷", "诉讼仲裁", "civil_flow", 13),
    ("破产重整", "诉讼仲裁", "civil_flow", 14),
    ("仲裁案件", "诉讼仲裁", "arbitration", 15),
    ("执行案件", "诉讼仲裁", "enforcement", 16),
    ("刑事辩护", "诉讼仲裁", "criminal", 17),
    ("行政诉讼", "诉讼仲裁", "administrative", 18),
    # —— 非诉业务（Phase 阶段制流程，不套用民诉法审限）——
    ("常年法律顾问", "非诉业务", "nonlit_retainer", 20),
    ("合同审查与起草", "非诉业务", "nonlit_contract", 21),
    ("公司设立与变更", "非诉业务", "nonlit_corporate", 22),
    ("股权架构设计", "非诉业务", "nonlit_corporate", 23),
    ("投融资并购", "非诉业务", "nonlit_ma", 24),
    ("尽职调查", "非诉业务", "nonlit_dd", 25),
    ("增资扩股", "非诉业务", "nonlit_ma", 26),
    ("改制重组", "非诉业务", "nonlit_ma", 27),
    ("劳动人事合规", "非诉业务", "nonlit_hr", 28),
    ("规章制度制定", "非诉业务", "nonlit_hr", 29),
    ("知识产权布局", "非诉业务", "nonlit_ip", 30),
    ("商标/专利申请", "非诉业务", "nonlit_ip", 31),
    ("税务筹划", "非诉业务", "nonlit_tax", 32),
    ("法律意见书", "非诉业务", "nonlit_opinion", 33),
    ("律师函/催告函", "非诉业务", "nonlit_letter", 34),
    ("谈判与调解", "非诉业务", "nonlit_negotiation", 35),
    ("发债与上市", "非诉业务", "nonlit_capital", 36),
    ("私募基金", "非诉业务", "nonlit_fund", 37),
    ("破产清算（管理人）", "非诉业务", "nonlit_bankruptcy", 38),
    ("合规体系建设", "非诉业务", "nonlit_compliance", 39),
    ("数据合规与个人信息保护", "非诉业务", "nonlit_datacompliance", 40),
    ("涉外法律服务", "非诉业务", "nonlit_foreign", 41),
    ("公证与见证", "非诉业务", "nonlit_notary", 42),
    ("法律培训", "非诉业务", "nonlit_training", 43),
    ("家族财富管理", "非诉业务", "nonlit_wealth", 44),
]


def _seed_case_types():
    n = query_one("SELECT COUNT(*) c FROM case_types")["c"]
    if n:
        return
    for name, cat, flow, sort in BUILTIN_CASE_TYPES:
        execute("INSERT OR IGNORE INTO case_types(name,category,flow,builtin,enabled,sort,created)"
                " VALUES(?,?,?,?,?,?,?)", (name, cat, flow, 1, 1, sort, now()))


# ---------------- 默认功能导航顺序 ----------------
DEFAULT_NAV = [
    {"key": "home", "name": "工作台首页", "icon": "home", "enabled": True},
    {"key": "cases", "name": "案件管理", "icon": "cases", "enabled": True},
    {"key": "intake", "name": "接案笔录", "icon": "intake", "enabled": True},
    {"key": "clients", "name": "客户管理", "icon": "clients", "enabled": True},
    {"key": "vault", "name": "档案库", "icon": "vault", "enabled": True},
    {"key": "graph", "name": "关系图谱", "icon": "graph", "enabled": True},
    {"key": "revenue", "name": "创收管理", "icon": "revenue", "enabled": True},
    {"key": "invoice", "name": "发票管理", "icon": "invoice", "enabled": True},
    {"key": "calendar", "name": "日程日历", "icon": "calendar", "enabled": True},
    {"key": "timer", "name": "计时工时", "icon": "timer", "enabled": True},
    {"key": "ai", "name": "AI 助手", "icon": "ai", "enabled": True},
    {"key": "remind", "name": "提醒中心", "icon": "remind", "enabled": True},
    {"key": "settings", "name": "设置", "icon": "settings", "enabled": True},
    {"key": "about", "name": "关于我", "icon": "about", "enabled": True},
]


def _seed_nav_order():
    if kv_get("nav_order") is None:
        kv_set("nav_order", DEFAULT_NAV)
    else:
        saved = kv_get("nav_order")
        if not isinstance(saved, list):
            kv_set("nav_order", DEFAULT_NAV)
            return
        changed = False
        # 迁移：移除已下线功能（如通讯录）
        if any((n.get("key") == "contacts") for n in saved):
            saved = [n for n in saved if n.get("key") != "contacts"]
            changed = True
        # 迁移：补入新版本新增的功能（保留用户已有排序，新功能追加到末尾）
        have = {n.get("key") for n in saved}
        for n in DEFAULT_NAV:
            if n["key"] not in have:
                saved.append(dict(n))
                changed = True
        if changed:
            kv_set("nav_order", saved)


# ---------------- 通用辅助 ----------------
def upsert(table: str, key_field: str, row: dict[str, Any]) -> None:
    cols = list(row.keys())
    placeholders = ",".join("?" for _ in cols)
    updates = ",".join(f"{c}=excluded.{c}" for c in cols if c != key_field)
    sql = (f"INSERT INTO {table} ({','.join(cols)}) VALUES ({placeholders}) "
           f"ON CONFLICT({key_field}) DO UPDATE SET {updates}")
    with _LOCK, CONN:
        CONN.execute(sql, [row[c] for c in cols])


def query(sql: str, params: tuple = ()) -> list[dict]:
    with _LOCK:
        cur = CONN.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def query_one(sql: str, params: tuple = ()) -> Optional[dict]:
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params: tuple = ()) -> None:
    with _LOCK, CONN:
        CONN.execute(sql, params)


def insert(table: str, row: dict[str, Any]) -> int:
    cols = list(row.keys())
    sql = f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})"
    with _LOCK, CONN:
        cur = CONN.execute(sql, [row[c] for c in cols])
        return int(cur.lastrowid)


def kv_get(k: str, default=None):
    row = query_one("SELECT v FROM kv WHERE k=?", (k,))
    if not row:
        return default
    try:
        return json.loads(row["v"])
    except Exception:
        return row["v"]


def kv_set(k: str, v: Any) -> None:
    upsert("kv", "k", {"k": k, "v": json.dumps(v, ensure_ascii=False)})


def audit(action: str, detail: str = "") -> None:
    """审计日志同时落 SQLite 与本地日志文件，便于溯源。"""
    from .config import AUDIT_PATH
    ts = now()
    line = f"[{ts}] {action} | {detail}\n"
    try:
        with open(AUDIT_PATH, "a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass
