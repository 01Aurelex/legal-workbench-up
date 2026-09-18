# -*- coding: utf-8 -*-
"""Obsidian 式本地 Markdown 档案库：YAML-frontmatter(子集)、[[双链]]、反向链接、关系图谱、全文检索。"""
from __future__ import annotations
import hashlib
import os
import re
from datetime import datetime
from pathlib import Path

from .config import VAULT_DIR
from . import db

WIKI_RE = re.compile(r"\[\[([^\[\]]+?)\]\]")
FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.S)


def rel(p: Path) -> str:
    return p.relative_to(VAULT_DIR).as_posix()


def abs_path(rel_path: str) -> Path:
    p = (VAULT_DIR / rel_path).resolve()
    if VAULT_DIR.resolve() not in p.parents and p != VAULT_DIR.resolve():
        raise ValueError("路径越界")
    return p


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """解析简单 key: value YAML 头（不引入第三方依赖，足够本工作台使用）。"""
    m = FM_RE.match(text)
    fm: dict[str, str] = {}
    body = text
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                fm[k.strip()] = v.strip().strip('"').strip("'")
        body = text[m.end():]
    return fm, body


def dump_frontmatter(fm: dict, body: str) -> str:
    lines = ["---"]
    for k, v in fm.items():
        lines.append(f"{k}: {v}")
    lines.append("---")
    lines.append("")
    return "\n".join(lines) + body.lstrip("\n")


def extract_links(body: str) -> list[str]:
    out = []
    for raw in WIKI_RE.findall(body):
        target = raw.split("|", 1)[0].strip()
        if target and target not in out:
            out.append(target)
    return out


def title_of(rel_path: str, fm: dict, body: str) -> str:
    if fm.get("标题") or fm.get("title"):
        return fm.get("标题") or fm.get("title")
    stem = Path(rel_path).stem
    h = re.search(r"^#\s+(.+)$", body, re.M)
    return h.group(1).strip() if h else stem


def scan_file(p: Path) -> dict:
    text = p.read_text(encoding="utf-8")
    fm, body = parse_frontmatter(text)
    rp = rel(p)
    st = p.stat()
    links = extract_links(body)
    ftype = fm.get("type") or _infer_folder(rp)
    row = {
        "rel_path": rp,
        "title": title_of(rp, fm, body),
        "ftype": ftype,
        "mtime": st.st_mtime,
        "size": st.st_size,
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "frontmatter": __import__("json").dumps(fm, ensure_ascii=False),
        "body": body,
        "updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    db.upsert("files", "rel_path", row)
    db.execute("DELETE FROM links WHERE src=?", (rp,))
    for dst in links:
        db.execute("INSERT INTO links(src,dst,anchor) VALUES(?,?,?)", (rp, dst, ""))
    if ftype == "case":
        _index_case(rp, fm)
    return row


def _infer_folder(rp: str) -> str:
    top = rp.split("/", 1)[0]
    return {"客户": "client", "案件": "case", "材料": "material",
            "文书": "doc", "笔记": "note", "法律库": "law"}.get(top, "note")


def _index_case(rp: str, fm: dict) -> None:
    db.upsert("cases", "rel_path", {
        "rel_path": rp,
        "client": fm.get("客户", ""),
        "client_path": fm.get("客户链接", ""),
        "cause": fm.get("案由", ""),
        "court": fm.get("管辖法院", ""),
        "procedure": fm.get("程序", "普通程序"),
        "stage": fm.get("阶段", "立案"),
        "case_no": fm.get("案号", ""),
        "filing_date": fm.get("立案日期", ""),
        "hearing_date": fm.get("开庭日期", ""),
        "judgment_date": fm.get("判决日期", ""),
        "judgment_eff_date": fm.get("生效日期", ""),
        "updated": db.now(),
    })


def scan_vault() -> dict:
    seen = set()
    n_links = 0
    for p in VAULT_DIR.rglob("*.md"):
        scan_file(p)
        seen.add(rel(p))
    # 清理已删除文件的索引
    for row in db.query("SELECT rel_path FROM files"):
        if row["rel_path"] not in seen and not abs_path_safe(row["rel_path"]).exists():
            db.execute("DELETE FROM files WHERE rel_path=?", (row["rel_path"],))
            db.execute("DELETE FROM links WHERE src=?", (row["rel_path"],))
            db.execute("DELETE FROM cases WHERE rel_path=?", (row["rel_path"],))
    n_links = db.query_one("SELECT COUNT(*) c FROM links")["c"]
    db.kv_set("vault_last_scan", db.now())
    return {"files": len(seen), "links": n_links}


def abs_path_safe(rel_path: str) -> Path:
    try:
        return abs_path(rel_path)
    except Exception:
        return VAULT_DIR / rel_path


def resolve_link(target: str) -> str | None:
    """把 [[双链目标]] 解析为实际 rel_path（支持标题/文件名/相对路径多种写法）。"""
    t = target.strip()
    candidates = [t, f"{t}.md", f"客户/{t}.md", f"案件/{t}.md",
                  f"材料/{t}.md", f"文书/{t}.md", f"笔记/{t}.md"]
    for c in candidates:
        p = VAULT_DIR / c
        if p.is_file():
            return rel(p)
    row = db.query_one("SELECT rel_path FROM files WHERE title=? LIMIT 1", (t,))
    return row["rel_path"] if row else None


def backlinks(rel_path: str) -> list[dict]:
    row = db.query_one("SELECT title FROM files WHERE rel_path=?", (rel_path,))
    title = row["title"] if row else None
    stem = Path(rel_path).stem
    no_ext = rel_path[:-3] if rel_path.endswith(".md") else rel_path
    targets = {rel_path, no_ext, stem, Path(no_ext).name}
    if title:
        targets.add(title)
    marks = ",".join("?" for _ in targets)
    out = []
    for r in db.query(f"SELECT DISTINCT src FROM links WHERE dst IN ({marks})", tuple(targets)):
        f = db.query_one("SELECT title,ftype FROM files WHERE rel_path=?", (r["src"],))
        if f:
            out.append({"rel_path": r["src"], "title": f["title"], "ftype": f["ftype"]})
    return out


def graph_data() -> dict:
    nodes, edges, ids = [], [], set()
    edge_set = set()

    def add_edge(a, b):
        if a and b and a != b and (a, b) not in edge_set and (b, a) not in edge_set:
            edge_set.add((a, b))
            edges.append({"from": a, "to": b})

    # 1) 文件节点
    for r in db.query("SELECT rel_path,title,ftype FROM files"):
        ids.add(r["rel_path"])
        nodes.append({"id": r["rel_path"], "label": r["title"], "group": r["ftype"] or "note"})

    # 2) 双链边（客户↔案件↔材料↔文书 等）
    for r in db.query("SELECT src,dst FROM links"):
        dst = resolve_link(r["dst"]) or r["dst"]
        if r["src"] in ids and dst in ids:
            add_edge(r["src"], dst)

    # 3) 案件 → 案由 → 法条（程序法依据流程映射，实体法依据案由/类型关键词智能关联）
    for c in db.query("SELECT rel_path, cause, case_type, case_category FROM cases"):
        cause = (c["cause"] or "").strip()
        if not cause or c["rel_path"] not in ids:
            continue
        cause_id = f"cause::{cause}"
        if cause_id not in ids:
            ids.add(cause_id)
            nodes.append({"id": cause_id, "label": cause, "group": "cause"})
        add_edge(c["rel_path"], cause_id)

        flow = _flow_of_case_row(c)
        law_names = list(FLOW_LAWS.get(flow, []))
        # 实体法：按案由文本与案件类型名做关键词命中（如"离婚协议"+"婚姻家庭"→民法典婚姻家庭编）
        # 注意不使用业务类别文本（"诉讼仲裁"含"仲裁"会造成误匹配）
        for law in cause_laws(f"{cause} {c.get('case_type') or ''}"):
            if law not in law_names:
                law_names.append(law)
        for law_name in law_names:
            law_id = f"law::{law_name}"
            if law_id not in ids:
                ids.add(law_id)
                nodes.append({"id": law_id, "label": law_name, "group": "law"})
            add_edge(cause_id, law_id)

    return {"nodes": nodes, "edges": edges}


# 流程 → 适用程序法（关系图谱：案由节点挂接的程序法依据）
FLOW_LAWS = {
    "civil_flow": ["民事诉讼法", "民诉法解释", "民事诉讼证据若干规定", "律师法"],
    "criminal": ["刑事诉讼法", "刑诉法解释", "律师法"],
    "administrative": ["行政诉讼法", "行政诉讼法解释", "律师法"],
    "arbitration": ["仲裁法", "律师法"],
    "enforcement": ["民事诉讼法", "强制执行相关规定", "律师法"],
}

# 案由/业务关键词 → 实体法（智能关联：离婚→民法典婚姻家庭编；劳动→劳动法/劳动合同法 等）
# 顺序即优先级：越具体的规则越靠前
CAUSE_LAW_RULES: list[tuple[list[str], list[str]]] = [
    (["离婚", "婚姻", "夫妻", "结婚", "抚养", "扶养", "赡养", "收养", "监护",
      "探望", "彩礼", "同居", "家暴", "家庭暴力", "亲子"],
     ["民法典·婚姻家庭编"]),
    (["继承", "遗嘱", "遗产", "遗赠", "法定继承"],
     ["民法典·继承编"]),
    (["工伤", "劳动", "劳动合同", "竞业限制", "辞退", "解雇", "经济补偿",
      "加班费", "工资争议", "确认劳动关系", "社保争议"],
     ["劳动法", "劳动合同法", "劳动争议调解仲裁法"]),
    (["民间借贷", "金融借款", "借款", "贷款", "保证合同", "担保", "抵押", "质押", "保理"],
     ["民法典·合同编", "民法典·物权编"]),
    (["买卖", "合同纠纷", "租赁", "承揽", "服务合同", "违约", "定金",
      "委托合同", "合伙", "赠与", "中介", "建设工程", "施工", "工程款"],
     ["民法典·合同编"]),
    (["侵权", "交通事故", "人身损害", "医疗损害", "产品责任", "产品质量",
      "名誉权", "肖像权", "隐私权", "个人信息", "网络侵权", "饲养动物"],
     ["民法典·侵权责任编"]),
    (["物权", "所有权", "相邻", "宅基地", "土地承包", "建筑物区分",
      "房屋买卖", "房屋租赁", "商品房", "物业", "业主"],
     ["民法典·物权编"]),
    (["公司", "股权", "股东", "出资", "分红", "知情权", "解散", "董事", "高管"],
     ["公司法"]),
    (["破产", "重整", "和解债权"],
     ["企业破产法"]),
    (["商标", "专利", "著作权", "版权", "知识产权", "不正当竞争", "商业秘密"],
     ["商标法", "专利法", "著作权法", "反不正当竞争法"]),
    (["票据", "汇票", "本票", "支票"],
     ["票据法"]),
    (["刑事", "诈骗", "盗窃", "故意伤害", "危险驾驶"],
     ["刑法"]),
    (["行政复议", "行政处罚", "行政强制", "行政许可", "政府信息公开"],
     ["行政复议法", "行政诉讼法"]),
    (["仲裁"],
     ["仲裁法"]),
    (["税务", "税收", "偷税", "发票违法"],
     ["税收征收管理法"]),
    (["消费者", "消费欺诈", "食品安全"],
     ["消费者权益保护法", "食品安全法"]),
]


def cause_laws(text: str) -> list[str]:
    """根据案由/类型文本匹配应关联的实体法（去重保序）。"""
    text = text or ""
    out: list[str] = []
    for keywords, laws in CAUSE_LAW_RULES:
        if any(k in text for k in keywords):
            for law in laws:
                if law not in out:
                    out.append(law)
    return out


def _flow_of_case_row(c: dict) -> str:
    """从案件类型反查流程 key（案件表无 flow 列，需经 case_types 映射）。"""
    if c.get("case_type"):
        t = db.query_one("SELECT flow FROM case_types WHERE name=?", (c["case_type"],))
        if t and t["flow"]:
            return t["flow"]
    if c.get("case_category") == "非诉业务":
        return "nonlit_generic"
    return "civil_flow"


def search(keyword: str) -> list[dict]:
    kw = keyword.strip().lower()
    if not kw:
        return []
    hits = []
    for r in db.query("SELECT rel_path,title,ftype,body,frontmatter FROM files"):
        hay = (r["title"] + "\n" + (r["body"] or "") + "\n" + (r["frontmatter"] or "")).lower()
        if kw in hay:
            i = hay.find(kw)
            snippet = (r["body"] or "")[max(0, i - 20): i + 60].replace("\n", " ")
            hits.append({"rel_path": r["rel_path"], "title": r["title"],
                         "ftype": r["ftype"], "snippet": snippet})
    return hits[:50]


def write_note(rel_path: str, text: str, fm: dict | None = None) -> str:
    p = abs_path(rel_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if fm is not None:
        _, body = parse_frontmatter(text)
        text = dump_frontmatter(fm, body)
    p.write_text(text, encoding="utf-8")
    scan_file(p)
    return rel(p)
