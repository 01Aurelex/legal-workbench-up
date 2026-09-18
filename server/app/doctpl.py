# -*- coding: utf-8 -*-
"""模板文书库：最高法《起诉状答辩状示范文本》226 份 + 诉讼保全模板 8 份。

- 模板文件存放 data/templates/（起诉状答辩状/<八大类>/…、诉讼保全/…），
  SQLite doc_templates 表仅做索引，删库可从文件重建；
- 一键生成：按既有命名规则（两位序号+客户+案由+类型+日期）把模板复制到
  案件文书目录并登记 gen_docs（沿用外部修改检测/飞书同步链路）；
- 推荐匹配：案由/案件类型 与模板案由 做精确/包含/二元组重叠评分，
  叠加案件流程 ↔ 模板大类映射（刑事/民商事/行政/执行）与诉讼保全场景加分。
"""
from __future__ import annotations

import re
import shutil
from copy import deepcopy
from pathlib import Path

from .config import TPL_DIR, DOCX_DIR, VAULT_DIR
from . import db, docgen

# 文书类型后缀（按长度降序匹配，避免「民事起诉状」被「起诉状」抢先）
KINDS = [
    "刑事（附带民事）自诉答辩状",
    "刑事（附带民事）自诉状",
    "第三人意见陈述书",
    "国家赔偿申请书", "国家赔偿答辩状",
    "民事起诉状", "民事答辩状",
    "行政起诉状", "行政答辩状",
    "担保书", "担保函",
    "起诉状", "答辩状", "申请书", "意见书",
]

# 模板大类 ↔ 案件流程映射（用于推荐加分）
CAT_FLOW = {
    "1.刑事（自诉）案件": "criminal",
    "2.民商事": "civil_flow",
    "3.知识产权": "civil_flow",
    "4.海事案件": "civil_flow",
    "5.环境资源案件": "civil_flow",
    "7.国家赔偿案件": "civil_flow",
    "6.行政案件": "administrative",
    "8.执行": "enforcement",
}

# 案件类型 → 模板案由关键词（与前端 TYPE_ALIASES 保持一致的方向）
TYPE_CAUSE_KEYS = {
    "婚姻家庭": ["离婚", "抚养", "扶养", "赡养", "收养", "彩礼", "同居"],
    "继承纠纷": ["继承", "遗嘱", "遗产", "遗赠"],
    "劳动争议": ["劳动", "工伤", "社保", "竞业"],
    "合同纠纷": ["合同", "违约", "服务", "承揽", "委托"],
    "买卖合同纠纷": ["买卖", "购销", "货款", "供货"],
    "民间借贷": ["民间借贷", "借款", "借条", "欠条"],
    "金融借款": ["金融借款", "信用卡", "银行"],
    "侵权责任纠纷": ["侵权", "损害", "交通事故", "医疗", "名誉", "隐私", "产品责任"],
    "房屋买卖/租赁": ["房屋买卖", "房屋租赁", "商品房", "物业", "房屋"],
    "建设工程": ["建设工程", "施工", "工程"],
    "公司股权纠纷": ["公司", "股权", "股东", "出资"],
    "知识产权": ["商标", "专利", "著作权", "版权", "商业秘密", "不正当竞争", "垄断", "邻接权"],
    "破产重整": ["破产", "重整"],
    "仲裁案件": ["仲裁"],
    "执行案件": ["执行", "强制执行", "参与分配", "优先购买权", "失信"],
    "刑事辩护": ["刑事", "自诉", "侮辱", "诽谤", "重婚", "拒不执行"],
    "行政诉讼": ["行政", "行政处罚", "行政许可", "征收", "政府信息公开", "行政复议", "行政强制", "行政协议", "行政补偿", "行政赔偿", "法定职责"],
}


def _bigrams(s: str) -> set[str]:
    s = re.sub(r"\s+", "", (s or "").lower())
    return {s[i:i + 2] for i in range(len(s) - 1)}


def parse_name(stem: str) -> dict:
    """解析模板文件名 → {name, cause, kind, is_example}。

    形如「17.离婚纠纷民事起诉状实例」「1、诉中财产保全申请书」「担保函-房产(1)」。
    """
    is_example = 0
    s = stem.strip()
    if s.endswith("实例"):
        is_example = 1
        s = s[:-2]
    s = re.sub(r"^\d+\s*[.、．]\s*", "", s)          # 去掉序号
    s = re.sub(r"[\(（]\d+[\)）]$", "", s).strip()    # 去掉尾部 (1)
    if s.endswith("模板"):
        s = s[:-2]
    kind, cause = "其他", ""
    for k in KINDS:
        if s.endswith(k) and len(s) > len(k):
            kind = k
            cause = s[: -len(k)].rstrip("的")
            break
        if s == k:                                    # 无案由的通用文书（如「行政答辩状」）
            kind = k
            cause = ""
            break
    else:
        # 担保类模板：类型词在名称中间（如「诉讼财产保全担保书-现金、存折」）
        for k in ("担保书", "担保函"):
            if k in s:
                kind = k
                break
    return {"name": s, "cause": cause, "kind": kind, "is_example": is_example}


def sync_templates() -> int:
    """扫描 data/templates/ 并重建 doc_templates 索引（以文件为准）。"""
    rows = {}
    for p in sorted(TPL_DIR.rglob("*.docx")):
        rel = p.relative_to(TPL_DIR).as_posix()
        parts = rel.split("/")
        grp = parts[0] if parts[0] in ("起诉状答辩状", "诉讼保全") else "诉讼保全"
        category = parts[1] if len(parts) > 2 else grp
        info = parse_name(p.stem)
        rows[rel] = {
            "rel_path": rel, "grp": grp, "category": category,
            "name": info["name"], "cause": info["cause"], "kind": info["kind"],
            "is_example": info["is_example"], "title": "",
            "updated": db.now(),
        }
    existing = {r["rel_path"] for r in db.query("SELECT rel_path FROM doc_templates")}
    for rel, row in rows.items():
        if rel in existing:
            db.execute(
                "UPDATE doc_templates SET grp=?,category=?,name=?,cause=?,kind=?,"
                "is_example=?,updated=? WHERE rel_path=?",
                (row["grp"], row["category"], row["name"], row["cause"], row["kind"],
                 row["is_example"], row["updated"], rel))
        else:
            db.insert("doc_templates", row)
    stale = existing - set(rows)
    for rel in stale:
        db.execute("DELETE FROM doc_templates WHERE rel_path=?", (rel,))
    return len(rows)


def list_templates(q: str = "", group: str = "", category: str = "") -> dict:
    """模板列表 + 分组统计（分组/分类/类型），支持关键字过滤。"""
    sql, args = "SELECT * FROM doc_templates WHERE 1=1", []
    if group:
        sql += " AND grp=?"; args.append(group)
    if category:
        sql += " AND category=?"; args.append(category)
    if q:
        sql += " AND (name LIKE ? OR cause LIKE ? OR kind LIKE ?)"
        args += [f"%{q}%"] * 3
    sql += " ORDER BY rel_path"
    templates = db.query(sql, tuple(args))
    all_rows = db.query("SELECT grp, category, COUNT(*) c FROM doc_templates GROUP BY grp, category")
    groups: dict[str, list] = {}
    for r in all_rows:
        groups.setdefault(r["grp"], []).append({"category": r["category"], "count": r["c"]})
    return {"templates": templates, "groups": groups, "total": db.query_one(
        "SELECT COUNT(*) c FROM doc_templates")["c"]}


def _case_flow(case_path: str) -> str:
    row = db.query_one("SELECT * FROM cases WHERE rel_path=?", (case_path,)) or {}
    return row.get("flow") or ""


def recommend(case_path: str, limit: int = 12) -> list[dict]:
    """按案件上下文（案由/案件类型/流程）给模板打分排序。"""
    from . import vault
    fm, _ = vault.parse_frontmatter(vault.abs_path(case_path).read_text(encoding="utf-8"))
    row = db.query_one("SELECT * FROM cases WHERE rel_path=?", (case_path,)) or {}
    cause = (fm.get("案由") or "").strip()
    ctype = (row.get("case_type") or fm.get("案件类型") or "").strip()
    flow = row.get("flow") or ""
    nonlit = (fm.get("业务类别") == "非诉业务") or str(flow).startswith("nonlit")
    text = f"{cause} {ctype}"

    out = []
    for t in db.query("SELECT * FROM doc_templates"):
        s, why = 0, []
        tc = (t["cause"] or "").strip()
        if tc and cause:
            if tc == cause:
                s += 100; why.append("案由一致")
            elif tc in cause or cause in tc:
                s += 70; why.append("案由相近")
            else:
                hits = len(_bigrams(tc) & _bigrams(cause))
                if hits >= 2:
                    s += min(40, hits * 6); why.append("案由相关")
        # 案件类型关键词命中模板案由
        for kw in TYPE_CAUSE_KEYS.get(ctype, []):
            if kw in tc or kw in (t["name"] or ""):
                s += 55; why.append(f"匹配{ctype}")
                break
        # 流程 ↔ 大类
        cat_flow = CAT_FLOW.get(t["category"] or "", "")
        if flow and cat_flow and cat_flow == flow:
            s += 15; why.append("业务对口")
        # 诉讼保全：所有诉讼案件都可能需要
        if t["grp"] == "诉讼保全" and not nonlit:
            s += 30; why.append("诉讼保全")
        # 示例文书靠后
        if t["is_example"]:
            s -= 25
        if s >= 20:
            out.append({**t, "score": s, "why": "、".join(dict.fromkeys(why)) or "推荐"})
    out.sort(key=lambda x: -x["score"])
    return out[:limit]


def preview(template_id: int, max_chars: int = 1200) -> str:
    """提取模板正文预览（段落 + 表格单元格文本）。"""
    from docx import Document
    t = db.query_one("SELECT * FROM doc_templates WHERE id=?", (template_id,))
    if not t:
        raise FileNotFoundError("模板不存在")
    p = TPL_DIR / t["rel_path"]
    if not p.exists():
        raise FileNotFoundError("模板文件缺失：" + t["rel_path"])
    doc = Document(p)
    parts = []
    for para in doc.paragraphs:
        txt = para.text.strip()
        if txt:
            parts.append(txt)
        if sum(len(x) for x in parts) > max_chars:
            break
    for tbl in doc.tables:
        for r in tbl.rows:
            cells = [c.text.strip() for c in r.cells if c.text.strip()]
            if cells:
                parts.append("｜".join(cells))
        if sum(len(x) for x in parts) > max_chars * 2:
            break
    return "\n".join(parts)[:max_chars * 2]


def generate(template_id: int, case_path: str) -> dict:
    """一键生成：复制模板到案件文书目录，按命名规则重命名并登记 gen_docs。"""
    from . import vault
    t = db.query_one("SELECT * FROM doc_templates WHERE id=?", (template_id,))
    if not t:
        raise FileNotFoundError("模板不存在")
    src = TPL_DIR / t["rel_path"]
    if not src.exists():
        raise FileNotFoundError("模板文件缺失：" + t["rel_path"])

    fm, _ = vault.parse_frontmatter(vault.abs_path(case_path).read_text(encoding="utf-8"))
    client, cause = fm.get("客户", ""), fm.get("案由", "")
    # 文件名里的类型：模板名去掉与案件案由重复的前缀（如「离婚纠纷民事起诉状」→「民事起诉状」）
    label = t["name"] or t["kind"]
    if t["cause"] and cause and label.startswith(cause):
        label = label[len(cause):] or t["name"]

    seq = docgen.next_seq(case_path)
    filename = docgen.build_filename(seq, client, cause, label)
    case_dir = DOCX_DIR / docgen.safe_name(f"{client}{cause}")
    case_dir.mkdir(parents=True, exist_ok=True)
    out = case_dir / filename
    shutil.copy2(src, out)

    rel_path = out.relative_to(VAULT_DIR).as_posix()
    digest = docgen.hash_file(out)
    db.execute(
        "INSERT INTO gen_docs(case_path,seq,doc_type,filename,rel_path,created,"
        "system_hash,disk_hash,sync_state,template_id) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (case_path, seq, label, filename, rel_path, db.now(), digest, digest,
         "一致", template_id))
    db.audit("模板生成文书", f"{filename} <- {t['name']} ({case_path})")
    return {"filename": filename, "rel_path": rel_path, "seq": seq,
            "abs_path": str(out), "template": t["name"], "doc_type": label}


# ==================== 要素式表单：自动抽取 + 回填生成（v0.9.7） ====================

def _cell_text(cell) -> str:
    return "\n".join(p.text for p in cell.paragraphs)


def _replace_text_in_paragraph(paragraph, pattern: str, repl: str, regex: bool = False) -> bool:
    """在段落的所有 w:t 文本节点上整体做（正则）替换，结果写入第一个文本节点并清空其余。

    这样可以避免 run 被拆分导致 simple string replace 失效，同时最大限度保留原 run 的字体格式。
    """
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    t_elems = [t for run in paragraph.runs for t in run._element.findall(".//w:t", ns)]
    if not t_elems:
        return False
    full = "".join(t.text or "" for t in t_elems)
    if regex:
        new_full, n = re.subn(pattern, repl, full, count=1)
    else:
        new_full = full.replace(pattern, repl, 1)
        n = 0 if new_full == full else 1
    if not n and new_full == full:
        return False
    t_elems[0].text = new_full
    for t in t_elems[1:]:
        t.text = ""
    return True


def _find_cells(doc, table_hint: str = "", row_hint: str = "", cell_hint: str = ""):
    """按提示文本定位单元格。table_hint 匹配表格内任意文本，row_hint 匹配行首列文本，
    cell_hint 匹配目标单元格文本。返回 [(table_idx, row_idx, col_idx, cell)]。"""
    out = []
    for ti, tbl in enumerate(doc.tables):
        tbl_text = "\n".join(_cell_text(c) for r in tbl.rows for c in r.cells)
        if table_hint and table_hint not in tbl_text:
            continue
        for ri, row in enumerate(tbl.rows):
            if not row.cells:
                continue
            row_header = (row.cells[0].text or "").strip()
            if row_hint and row_hint not in row_header:
                continue
            for ci, cell in enumerate(row.cells):
                if cell_hint and cell_hint not in cell.text:
                    continue
                out.append((ti, ri, ci, cell))
    return out


# ---------- 离婚纠纷：自动归纳后固化的字段规则（MVP） ----------

_LIHUN_FIELDS = [
    # ===== 当事人信息 =====
    {"section": "当事人信息", "key": "plaintiff_name", "label": "原告姓名", "type": "text",
     "loc": {"table": "当事人信息", "row": "原告", "cell": "住所地（户籍所在地）", "para": 0},
     "gen": {"kind": "append", "label": "姓名："}},
    {"section": "当事人信息", "key": "plaintiff_gender", "label": "原告性别", "type": "radio",
     "options": ["男", "女"],
     "loc": {"table": "当事人信息", "row": "原告", "cell": "住所地（户籍所在地）", "para": 1},
     "gen": {"kind": "radio"}},
    {"section": "当事人信息", "key": "plaintiff_birthday", "label": "原告出生日期", "type": "date",
     "loc": {"table": "当事人信息", "row": "原告", "cell": "住所地（户籍所在地）", "para": 2},
     "gen": {"kind": "date"}},
    {"section": "当事人信息", "key": "plaintiff_ethnic", "label": "原告民族", "type": "text",
     "loc": {"table": "当事人信息", "row": "原告", "cell": "住所地（户籍所在地）", "para": 2},
     "gen": {"kind": "append", "label": "民族："}},
    {"section": "当事人信息", "key": "plaintiff_work_unit", "label": "原告工作单位", "type": "text",
     "loc": {"table": "当事人信息", "row": "原告", "cell": "住所地（户籍所在地）", "para": 3},
     "gen": {"kind": "append", "label": "工作单位："}},
    {"section": "当事人信息", "key": "plaintiff_job", "label": "原告职务", "type": "text",
     "loc": {"table": "当事人信息", "row": "原告", "cell": "住所地（户籍所在地）", "para": 3},
     "gen": {"kind": "append", "label": "职务："}},
    {"section": "当事人信息", "key": "plaintiff_phone", "label": "原告联系电话", "type": "text",
     "loc": {"table": "当事人信息", "row": "原告", "cell": "住所地（户籍所在地）", "para": 3},
     "gen": {"kind": "append", "label": "联系电话："}},
    {"section": "当事人信息", "key": "plaintiff_domicile", "label": "原告住所地（户籍所在地）", "type": "text",
     "loc": {"table": "当事人信息", "row": "原告", "cell": "住所地（户籍所在地）", "para": 4},
     "gen": {"kind": "append", "label": "住所地（户籍所在地）："}},
    {"section": "当事人信息", "key": "plaintiff_residence", "label": "原告经常居住地", "type": "text",
     "loc": {"table": "当事人信息", "row": "原告", "cell": "住所地（户籍所在地）", "para": 4},
     "gen": {"kind": "append", "label": "经常居住地："}},
    {"section": "当事人信息", "key": "plaintiff_id_type", "label": "原告证件类型", "type": "text",
     "loc": {"table": "当事人信息", "row": "原告", "cell": "住所地（户籍所在地）", "para": 5},
     "gen": {"kind": "append", "label": "证件类型："}},
    {"section": "当事人信息", "key": "plaintiff_id_no", "label": "原告证件号码", "type": "text",
     "loc": {"table": "当事人信息", "row": "原告", "cell": "住所地（户籍所在地）", "para": 5},
     "gen": {"kind": "append", "label": "证件号码："}},

    # ===== 被告信息 =====
    {"section": "被告信息", "key": "defendant_name", "label": "被告姓名", "type": "text",
     "loc": {"table": "被告", "row": "被告", "cell": "住所地（户籍所在地）", "para": 0},
     "gen": {"kind": "append", "label": "姓名："}},
    {"section": "被告信息", "key": "defendant_gender", "label": "被告性别", "type": "radio",
     "options": ["男", "女"],
     "loc": {"table": "被告", "row": "被告", "cell": "住所地（户籍所在地）", "para": 1},
     "gen": {"kind": "radio"}},
    {"section": "被告信息", "key": "defendant_birthday", "label": "被告出生日期", "type": "date",
     "loc": {"table": "被告", "row": "被告", "cell": "住所地（户籍所在地）", "para": 2},
     "gen": {"kind": "date"}},
    {"section": "被告信息", "key": "defendant_ethnic", "label": "被告民族", "type": "text",
     "loc": {"table": "被告", "row": "被告", "cell": "住所地（户籍所在地）", "para": 2},
     "gen": {"kind": "append", "label": "民族："}},
    {"section": "被告信息", "key": "defendant_work_unit", "label": "被告工作单位", "type": "text",
     "loc": {"table": "被告", "row": "被告", "cell": "住所地（户籍所在地）", "para": 3},
     "gen": {"kind": "append", "label": "工作单位："}},
    {"section": "被告信息", "key": "defendant_job", "label": "被告职务", "type": "text",
     "loc": {"table": "被告", "row": "被告", "cell": "住所地（户籍所在地）", "para": 3},
     "gen": {"kind": "append", "label": "职务："}},
    {"section": "被告信息", "key": "defendant_phone", "label": "被告联系电话", "type": "text",
     "loc": {"table": "被告", "row": "被告", "cell": "住所地（户籍所在地）", "para": 3},
     "gen": {"kind": "append", "label": "联系电话："}},
    {"section": "被告信息", "key": "defendant_domicile", "label": "被告住所地（户籍所在地）", "type": "text",
     "loc": {"table": "被告", "row": "被告", "cell": "住所地（户籍所在地）", "para": 4},
     "gen": {"kind": "append", "label": "住所地（户籍所在地）："}},
    {"section": "被告信息", "key": "defendant_residence", "label": "被告经常居住地", "type": "text",
     "loc": {"table": "被告", "row": "被告", "cell": "住所地（户籍所在地）", "para": 4},
     "gen": {"kind": "append", "label": "经常居住地："}},
    {"section": "被告信息", "key": "defendant_id_type", "label": "被告证件类型", "type": "text",
     "loc": {"table": "被告", "row": "被告", "cell": "住所地（户籍所在地）", "para": 5},
     "gen": {"kind": "append", "label": "证件类型："}},
    {"section": "被告信息", "key": "defendant_id_no", "label": "被告证件号码", "type": "text",
     "loc": {"table": "被告", "row": "被告", "cell": "住所地（户籍所在地）", "para": 5},
     "gen": {"kind": "append", "label": "证件号码："}},

    # ===== 委托诉讼代理人 =====
    {"section": "委托诉讼代理人", "key": "agent_has", "label": "是否有委托诉讼代理人", "type": "radio",
     "options": ["有", "无"],
     "loc": {"table": "委托诉讼代理人", "row": "委托诉讼代理人", "cell": "代理权限", "para": 0},
     "gen": {"kind": "radio"}},
    {"section": "委托诉讼代理人", "key": "agent_name", "label": "代理人姓名", "type": "text",
     "loc": {"table": "委托诉讼代理人", "row": "委托诉讼代理人", "cell": "代理权限", "para": 1},
     "gen": {"kind": "append", "label": "姓名："}},
    {"section": "委托诉讼代理人", "key": "agent_unit", "label": "代理人单位", "type": "text",
     "loc": {"table": "委托诉讼代理人", "row": "委托诉讼代理人", "cell": "代理权限", "para": 2},
     "gen": {"kind": "append", "label": "单位："}},
    {"section": "委托诉讼代理人", "key": "agent_job", "label": "代理人职务", "type": "text",
     "loc": {"table": "委托诉讼代理人", "row": "委托诉讼代理人", "cell": "代理权限", "para": 2},
     "gen": {"kind": "append", "label": "职务："}},
    {"section": "委托诉讼代理人", "key": "agent_phone", "label": "代理人联系电话", "type": "text",
     "loc": {"table": "委托诉讼代理人", "row": "委托诉讼代理人", "cell": "代理权限", "para": 2},
     "gen": {"kind": "append", "label": "联系电话："}},
    {"section": "委托诉讼代理人", "key": "agent_auth", "label": "代理权限", "type": "radio",
     "options": ["一般授权", "特别授权", "无"],
     "loc": {"table": "委托诉讼代理人", "row": "委托诉讼代理人", "cell": "代理权限", "para": 3},
     "gen": {"kind": "radio"}},

    # ===== 诉讼请求 =====
    {"section": "诉讼请求", "key": "claim_divorce", "label": "1. 解除婚姻关系（具体主张）", "type": "textarea",
     "loc": {"table": "解除婚姻关系", "row": "1. 解除婚姻关系", "cell": "具体主张", "para": 0},
     "gen": {"kind": "replace", "placeholder": "（具体主张）"}},
    {"section": "诉讼请求", "key": "property_has", "label": "2. 夫妻共同财产有无", "type": "radio",
     "options": ["无财产", "有财产"],
     "loc": {"table": "夫妻共同财产", "row": "2. 夫妻共同财产", "cell": "无财产", "para": 0},
     "gen": {"kind": "radio"}},
    {"section": "诉讼请求", "key": "house_owner", "label": "房屋归属", "type": "radio",
     "options": ["原告", "被告", "其他"],
     "loc": {"table": "夫妻共同财产", "row": "2. 夫妻共同财产", "cell": "房屋明细", "para": 1},
     "gen": {"kind": "radio"}},
    {"section": "诉讼请求", "key": "house_owner_other", "label": "房屋其他归属说明", "type": "text",
     "loc": {"table": "夫妻共同财产", "row": "2. 夫妻共同财产", "cell": "房屋明细", "para": 1},
     "gen": {"kind": "regex", "pattern": r"其他□\(\s*\)", "repl": "其他□({value})"}},
    {"section": "诉讼请求", "key": "car_owner", "label": "汽车归属", "type": "radio",
     "options": ["原告", "被告", "其他"],
     "loc": {"table": "夫妻共同财产", "row": "2. 夫妻共同财产", "cell": "汽车明细", "para": 2},
     "gen": {"kind": "radio"}},
    {"section": "诉讼请求", "key": "car_owner_other", "label": "汽车其他归属说明", "type": "text",
     "loc": {"table": "夫妻共同财产", "row": "2. 夫妻共同财产", "cell": "汽车明细", "para": 2},
     "gen": {"kind": "regex", "pattern": r"其他□\(\s*\)", "repl": "其他□({value})"}},
    {"section": "诉讼请求", "key": "deposit_owner", "label": "存款归属", "type": "radio",
     "options": ["原告", "被告", "其他"],
     "loc": {"table": "夫妻共同财产", "row": "2. 夫妻共同财产", "cell": "存款明细", "para": 3},
     "gen": {"kind": "radio"}},
    {"section": "诉讼请求", "key": "deposit_owner_other", "label": "存款其他归属说明", "type": "text",
     "loc": {"table": "夫妻共同财产", "row": "2. 夫妻共同财产", "cell": "存款明细", "para": 3},
     "gen": {"kind": "regex", "pattern": r"其他□\(\s*\)", "repl": "其他□({value})"}},
    {"section": "诉讼请求", "key": "debt_has", "label": "3. 夫妻共同债务有无", "type": "radio",
     "options": ["无债务", "有债务"],
     "loc": {"table": "夫妻共同债务", "row": "3. 夫妻共同债务", "cell": "无债务", "para": 0},
     "gen": {"kind": "radio"}},
    {"section": "诉讼请求", "key": "debt1", "label": "债务 1 内容", "type": "text",
     "loc": {"table": "夫妻共同债务", "row": "3. 夫妻共同债务", "cell": "债务 1", "para": 1},
     "gen": {"kind": "regex", "pattern": r"债务\s+1：\s+", "repl": "债务 1：{value}"}},
    {"section": "诉讼请求", "key": "debt1_owner", "label": "债务 1 承担主体", "type": "radio",
     "options": ["原告", "被告", "其他"],
     "loc": {"table": "夫妻共同债务", "row": "3. 夫妻共同债务", "cell": "债务 1", "para": 1},
     "gen": {"kind": "radio"}},
    {"section": "诉讼请求", "key": "debt2", "label": "债务 2 内容", "type": "text",
     "loc": {"table": "夫妻共同债务", "row": "3. 夫妻共同债务", "cell": "债务 2", "para": 2},
     "gen": {"kind": "regex", "pattern": r"债务\s+2：\s+", "repl": "债务 2：{value}"}},
    {"section": "诉讼请求", "key": "debt2_owner", "label": "债务 2 承担主体", "type": "radio",
     "options": ["原告", "被告", "其他"],
     "loc": {"table": "夫妻共同债务", "row": "3. 夫妻共同债务", "cell": "债务 2", "para": 2},
     "gen": {"kind": "radio"}},
    {"section": "诉讼请求", "key": "child_custody_has", "label": "4. 子女直接抚养问题", "type": "radio",
     "options": ["无此问题", "有此问题"],
     "loc": {"table": "子女直接抚养", "row": "4. 子女直接抚养", "cell": "无此问题", "para": 0},
     "gen": {"kind": "radio"}},
    {"section": "诉讼请求", "key": "child1", "label": "子女 1 姓名及归属", "type": "text",
     "loc": {"table": "子女直接抚养", "row": "4. 子女直接抚养", "cell": "子女 1", "para": 1},
     "gen": {"kind": "regex", "pattern": r"子女\s+1：\s+", "repl": "子女 1：{value}"}},
    {"section": "诉讼请求", "key": "child1_owner", "label": "子女 1 归属", "type": "radio",
     "options": ["原告", "被告"],
     "loc": {"table": "子女直接抚养", "row": "4. 子女直接抚养", "cell": "子女 1", "para": 1},
     "gen": {"kind": "radio"}},
    {"section": "诉讼请求", "key": "child2", "label": "子女 2 姓名及归属", "type": "text",
     "loc": {"table": "子女直接抚养", "row": "4. 子女直接抚养", "cell": "子女 2", "para": 2},
     "gen": {"kind": "regex", "pattern": r"子女\s+2：\s+", "repl": "子女 2：{value}"}},
    {"section": "诉讼请求", "key": "child2_owner", "label": "子女 2 归属", "type": "radio",
     "options": ["原告", "被告"],
     "loc": {"table": "子女直接抚养", "row": "4. 子女直接抚养", "cell": "子女 2", "para": 2},
     "gen": {"kind": "radio"}},
    {"section": "诉讼请求", "key": "child_support_has", "label": "5. 子女抚养费问题", "type": "radio",
     "options": ["无此问题", "有此问题"],
     "loc": {"table": "子女抚养费", "row": "5. 子女抚养费", "cell": "无此问题", "para": 0},
     "gen": {"kind": "radio"}},
    {"section": "诉讼请求", "key": "child_support_payer", "label": "抚养费承担主体", "type": "radio",
     "options": ["原告", "被告"],
     "loc": {"table": "子女抚养费", "row": "5. 子女抚养费", "cell": "抚养费承担主体", "para": 1},
     "gen": {"kind": "radio"}},
    {"section": "诉讼请求", "key": "child_support_amount", "label": "抚养费金额及明细", "type": "text",
     "loc": {"table": "子女抚养费", "row": "5. 子女抚养费", "cell": "抚养费承担主体", "para": 1},
     "gen": {"kind": "append", "label": "金额及明细："}},
    {"section": "诉讼请求", "key": "child_support_method", "label": "抚养费支付方式", "type": "text",
     "loc": {"table": "子女抚养费", "row": "5. 子女抚养费", "cell": "支付方式", "para": 2},
     "gen": {"kind": "append", "label": "支付方式："}},
    {"section": "诉讼请求", "key": "visitation_has", "label": "6. 探望权问题", "type": "radio",
     "options": ["无此问题", "有此问题"],
     "loc": {"table": "探望权", "row": "6. 探望权", "cell": "无此问题", "para": 0},
     "gen": {"kind": "radio"}},
    {"section": "诉讼请求", "key": "visitation_holder", "label": "探望权行使主体", "type": "radio",
     "options": ["原告", "被告"],
     "loc": {"table": "探望权", "row": "6. 探望权", "cell": "探望权行使主体", "para": 1},
     "gen": {"kind": "radio"}},
    {"section": "诉讼请求", "key": "visitation_method", "label": "探望权行使方式", "type": "text",
     "loc": {"table": "探望权", "row": "6. 探望权", "cell": "探望权行使主体", "para": 1},
     "gen": {"kind": "append", "label": "行使方式："}},
    {"section": "诉讼请求", "key": "compensation_type", "label": "7. 赔偿/补偿/经济帮助", "type": "radio",
     "options": ["无此问题", "离婚损害赔偿", "离婚经济补偿", "离婚经济帮助"],
     "loc": {"table": "离婚损害赔偿", "row": "7. 离婚损害赔偿", "cell": "无此问题", "para": 0},
     "gen": {"kind": "radio"}},
    {"section": "诉讼请求", "key": "compensation_amount", "label": "赔偿/补偿/帮助金额", "type": "text",
     "loc": {"table": "离婚损害赔偿", "row": "7. 离婚损害赔偿", "cell": "无此问题", "para": 1},
     "gen": {"kind": "append", "label": "金额："}},
    {"section": "诉讼请求", "key": "litigation_fee", "label": "8. 是否主张诉讼费用", "type": "radio",
     "options": ["是", "否"],
     "loc": {"table": "是否主张诉讼费用", "row": "8. 是否主张诉讼费用", "cell": "是□", "para": 0},
     "gen": {"kind": "radio"}},
    {"section": "诉讼请求", "key": "other_claims", "label": "9. 其他请求", "type": "textarea",
     "loc": {"table": "其他请求", "row": "9. 其他请求", "cell": "", "para": 0},
     "gen": {"kind": "clear_add", "prompt": ""}},
    {"section": "诉讼请求", "key": "pre_preservation", "label": "是否已经诉前保全", "type": "radio",
     "options": ["是", "否"],
     "loc": {"table": "是否已经诉前保全", "row": "是否已经诉前保全", "cell": "保全法院", "para": 0},
     "gen": {"kind": "radio"}},
    {"section": "诉讼请求", "key": "preservation_court", "label": "保全法院", "type": "text",
     "loc": {"table": "是否已经诉前保全", "row": "是否已经诉前保全", "cell": "保全法院", "para": 0},
     "gen": {"kind": "append", "label": "保全法院："}},
    {"section": "诉讼请求", "key": "preservation_time", "label": "保全时间", "type": "date",
     "loc": {"table": "是否已经诉前保全", "row": "是否已经诉前保全", "cell": "保全法院", "para": 0},
     "gen": {"kind": "append", "label": "保全时间："}},
    {"section": "诉讼请求", "key": "preservation_case_no", "label": "保全案号", "type": "text",
     "loc": {"table": "是否已经诉前保全", "row": "是否已经诉前保全", "cell": "保全法院", "para": 0},
     "gen": {"kind": "append", "label": "保全案号："}},

    # ===== 事实与理由 =====
    {"section": "事实与理由", "key": "fact_marriage", "label": "1. 婚姻关系基本情况", "type": "textarea",
     "loc": {"table": "婚姻关系基本情况", "row": "1. 婚姻关系基本情况", "cell": "结婚时间", "para": 0},
     "gen": {"kind": "replace", "placeholder": "结婚时间："}},
    {"section": "事实与理由", "key": "fact_property", "label": "2. 夫妻共同财产情况", "type": "textarea",
     "loc": {"table": "夫妻共同财产情况", "row": "2. 夫妻共同财产情况", "cell": "", "para": 0},
     "gen": {"kind": "clear_add", "prompt": ""}},
    {"section": "事实与理由", "key": "fact_debt", "label": "3. 夫妻共同债务情况", "type": "textarea",
     "loc": {"table": "夫妻共同债务情况", "row": "3. 夫妻共同债务情况", "cell": "", "para": 0},
     "gen": {"kind": "clear_add", "prompt": ""}},
    {"section": "事实与理由", "key": "fact_custody", "label": "4. 子女直接抚养情况", "type": "textarea",
     "loc": {"table": "子女直接抚养情况", "row": "4. 子女直接抚养情况", "cell": "子女应归", "para": 0},
     "gen": {"kind": "replace", "placeholder": "（子女应归原告或者被告直接抚养的事由）"}},
    {"section": "事实与理由", "key": "fact_support", "label": "5. 子女抚养费情况", "type": "textarea",
     "loc": {"table": "子女抚养费情况", "row": "5. 子女抚养费情况", "cell": "原告或者被告", "para": 0},
     "gen": {"kind": "replace", "placeholder": "（原告或者被告应支付抚养费及相应金额、支付方式的事由）"}},
    {"section": "事实与理由", "key": "fact_visitation", "label": "6. 子女探望权情况", "type": "textarea",
     "loc": {"table": "子女探望权情况", "row": "6. 子女探望权情况", "cell": "不直接抚养", "para": 0},
     "gen": {"kind": "replace", "placeholder": "（不直接抚养子女一方应否享有探望权以及具体行使方式的事由）"}},
    {"section": "事实与理由", "key": "fact_compensation", "label": "7. 赔偿/补偿/经济帮助相关情况", "type": "textarea",
     "loc": {"table": "赔偿", "row": "7. 赔 偿 / 补 偿 / 经 济 帮 助相关情况", "cell": "符合离婚", "para": 0},
     "gen": {"kind": "replace", "placeholder": "（符合离婚损害赔偿、离婚经济补偿或离婚经济帮助的相关事实等）"}},
    {"section": "事实与理由", "key": "fact_other", "label": "8. 其他", "type": "textarea",
     "loc": {"table": "其他", "row": "8. 其他", "cell": "", "para": 0},
     "gen": {"kind": "clear_add", "prompt": ""}},
    {"section": "事实与理由", "key": "legal_basis", "label": "9. 请求依据", "type": "textarea",
     "loc": {"table": "请求依据", "row": "9. 请求依据", "cell": "法律及司法解释", "para": 0},
     "gen": {"kind": "replace", "placeholder": "（法律及司法解释的规定，要写明具体条文）"}},
    {"section": "事实与理由", "key": "evidence_list", "label": "10. 证据清单", "type": "textarea",
     "loc": {"table": "证据清单", "row": "10. 证据清单", "cell": "", "para": 0},
     "gen": {"kind": "clear_add", "prompt": ""}},

    # ===== 调解意愿 =====
    {"section": "调解意愿", "key": "know_mediation", "label": "是否了解调解", "type": "radio",
     "options": ["了解", "不了解"],
     "loc": {"table": "对纠纷解决方式的意愿", "row": "是否了解调解", "cell": "了解", "para": 0},
     "gen": {"kind": "radio"}},
    {"section": "调解意愿", "key": "consider_mediation", "label": "是否考虑先行调解", "type": "radio",
     "options": ["是", "否", "暂不确定，想要了解更多内容"],
     "loc": {"table": "是否考虑先行调解", "row": "是否考虑先行调解", "cell": "暂不确定", "para": 0},
     "gen": {"kind": "radio"}},
]


def _lihun_schema():
    """返回离婚纠纷要素式表单 schema（按 section 分组，前端直接渲染）。"""
    sections = []
    for f in _LIHUN_FIELDS:
        sec = next((s for s in sections if s["title"] == f["section"]), None)
        if sec is None:
            sec = {"title": f["section"], "fields": []}
            sections.append(sec)
        sec["fields"].append({
            "key": f["key"], "label": f["label"], "type": f["type"],
            "options": f.get("options", []),
        })
    return {"cause": "离婚纠纷", "title": "离婚纠纷民事起诉状", "sections": sections}


def _apply_field(cell, para_idx: int, value, gen: dict):
    """根据 gen 规则把 value 写入单元格的指定段落。"""
    paras = list(cell.paragraphs)
    if para_idx >= len(paras):
        return
    p = paras[para_idx]
    kind = gen["kind"]
    val = (value or "").strip()

    if kind == "append":
        label = gen["label"]
        # 把 "label" + 空白 替换为 "label" + value + " "
        _replace_text_in_paragraph(p, re.escape(label) + r"\s*", f"{label}{val} ", regex=True)
    elif kind == "radio":
        # 自动识别段落中的 □ 选项：前面是行首/空格/斜杠/冒号的连续非分隔字符
        text = p.text
        opts = [m.group(1) for m in re.finditer(r"(?:^|[\s/：])([^\s/：]+?)□", text)]
        for opt in opts:
            old = f"{opt}□"
            new = f"{opt}{'☑' if opt == val else '□'}"
            _replace_text_in_paragraph(p, old, new)
    elif kind == "date":
        if val:
            try:
                from datetime import datetime
                d = datetime.strptime(val, "%Y-%m-%d")
                date_str = f"{d.year}年{d.month:02d}月{d.day:02d}日"
                # 替换 "出生日期：...年...月...日" 中的日期占位
                _replace_text_in_paragraph(
                    p, r"出生日期：\s*年\s*月\s*日\s*", f"出生日期：{date_str} ", regex=True)
            except Exception:
                pass
    elif kind == "replace":
        placeholder = gen.get("placeholder", "")
        if placeholder and val:
            _replace_text_in_paragraph(p, placeholder, val)
    elif kind == "clear_add":
        if val:
            _replace_text_in_paragraph(p, re.escape(p.text), val, regex=True)
    elif kind == "regex":
        pattern = gen["pattern"].replace("{value}", re.escape(val))
        repl = gen["repl"].replace("{value}", val)
        if val:
            _replace_text_in_paragraph(p, pattern, repl, regex=True)


def _fill_lihun(doc, values: dict):
    """按 values 回填离婚纠纷模板。"""
    for f in _LIHUN_FIELDS:
        loc = f["loc"]
        cells = _find_cells(doc,
                            table_hint=loc["table"],
                            row_hint=loc["row"],
                            cell_hint=loc["cell"])
        if not cells:
            continue
        for _ti, _ri, _ci, cell in cells:
            _apply_field(cell, loc["para"], values.get(f["key"]), f["gen"])


# ==================== 通用要素引擎：自动扫描任意示范文本（v0.9.10） ====================
#
# 最高法示范文本结构高度统一：若干张表格，分区横幅行（合并单元格）+「行标题｜填写区」行。
# 填写区段落只有四种形态：
#   1) 选项：男□ 女□（后缀式）或 □警告 □罚款（前缀式）；
#   2) 标签填空：姓名： / 单位：  职务：；
#   3) 日期：出生日期：    年   月   日；
#   4) 整格自由填写（空白单元格）→ textarea。
# 抽取与回填共用同一套定位（table/row/cell/paragraph），保证「所见即可填、所填即可回」。

_WS = re.compile(r"[ \t　\r\n]+")
# 后缀选项：选项文字紧跟 □（如 男□、刑事附带民事判决书□），冒号不进入选项名
_RE_OPT_SUFFIX = re.compile(r"([^\s□：:，,；;]+?)□")
# 前缀选项：□ 后紧跟选项文字（如 □警告）
_RE_OPT_PREFIX = re.compile(r"□\s*([^\s□，,；;]+)")
# 标签：2~20 个中英文字符后接全角冒号（允许标签内部带括号补充）
_RE_LABEL = re.compile(r"([一-龥A-Za-z0-9][一-龥A-Za-z0-9/、（）()]{1,19}?)：")
_RE_DATE_RUN = re.compile(r"年\s+月\s+日")
_RE_LEAD_NUM = re.compile(r"^[\d.、\s□]+")
# 可合并为同一单选组的互补选项
_BINARY_WORDS = {"是", "否", "有", "无", "男", "女", "确认", "异议", "了解", "不了解",
                 "同意", "不同意", "原告", "被告"}
# 单选语义的二元/少量选项集合（其余多选项按多选 check 处理）
_RADIO_SETS = [
    {"男", "女"}, {"是", "否"}, {"有", "无"}, {"原告", "被告"}, {"确认", "异议"},
    {"了解", "不了解"}, {"一般授权", "特别授权", "无"},
]


def _clean(s: str) -> str:
    return _WS.sub("", (s or "")).strip()


def _clean_space(s: str) -> str:
    return _WS.sub(" ", (s or "")).strip()


def _unique_cells(row):
    """合并单元格在 python-docx 中会重复出现，按底层 tc 去重并保持顺序。"""
    seen, out = set(), []
    for c in row.cells:
        if c._tc not in seen:
            seen.add(c._tc)
            out.append(c)
    return out


def _option_style_and_opts(text: str):
    """返回 (style, [(opt,start,end)], spans)。style: 'suffix'/'prefix'/None。"""
    if "□" not in text:
        return None, []
    i = text.index("□")
    before = text[:i].rstrip()
    suf = list(_RE_OPT_SUFFIX.finditer(text))
    pre = list(_RE_OPT_PREFIX.finditer(text))
    # 以第一个 □ 的形态判定整段风格
    if before and not before.endswith(("：", ":", " ")):
        opts = [(m.group(1), m.start(), m.end()) for m in suf]
        return ("suffix" if opts else None), opts
    if pre:
        return "prefix", [(m.group(1), m.start(), m.end()) for m in pre]
    if suf:
        return "suffix", [(m.group(1), m.start(), m.end()) for m in suf]
    return None, []


def _is_radio(opts: list[str]) -> bool:
    s = set(opts)
    if len(opts) <= 4:
        return True
    return any(s <= rs or s == rs for rs in _RADIO_SETS)


def _row_role(row_header: str) -> str:
    """行标题精简：去掉括号补充与序号前空白，作为字段前缀。"""
    h = _clean(row_header)
    h = re.sub(r"（.*?）", "", h)
    h = re.sub(r"\(.*?\)", "", h)
    return h.strip()


def _field_label(role: str, name: str) -> str:
    name = (name or "").strip()
    if role and not role[0].isdigit():
        if not name or name == role:
            return role
        return f"{role}｜{name}"
    return name or role


def _valid_label(lb: str) -> bool:
    """标签内括号必须成对，且不含 □ 等杂符。"""
    if "□" in lb:
        return False
    return lb.count("（") == lb.count("）") and lb.count("(") == lb.count(")")


def _clean_label_name(s: str) -> str:
    s = (s or "").replace("□", "")
    s = _RE_LEAD_NUM.sub("", s)
    return s.strip(" ：:、.")


def _generic_fields(doc):
    """扫描 doc，产出有序字段列表（schema 与回填共用，顺序即 key）。

    每项：{key,label,type,options,loc, _section}
    选项字段 loc={"t","r","locs":[{"c","p"}]} 可跨连续段落；
    其余字段 loc={"t","r","c","p","anchor"/"empty"}。
    """
    fields, seq = [], 0
    section = "基本信息"

    def add(ftype, label, options=None, loc=None):
        nonlocal seq
        fields.append({
            "key": f"g{seq}", "label": _clean_label_name(label)[:80], "type": ftype,
            "options": options or [], "loc": loc or {}, "_section": section,
        })
        seq += 1

    def labels_in(rest):
        out = []
        for m in _RE_LABEL.finditer(rest):
            lb = m.group(1)
            if _valid_label(lb):
                out.append((lb, m.start(), m.end()))
        return out

    for ti, tbl in enumerate(doc.tables):
        for ri, row in enumerate(tbl.rows):
            uniq = _unique_cells(row)
            texts = [_clean_space(c.text) for c in uniq]
            joined = _clean("".join(texts))
            # 1) 单格行：短的是分区横幅；长的是说明/示例文字，跳过
            if len(uniq) == 1:
                if joined and len(joined) <= 24 and "□" not in joined and "：" not in joined:
                    section = joined
                continue
            if len(uniq) < 2:
                continue
            role = _row_role(texts[0])
            consumed_cells = set()
            # 2) 预扫描「短标签格 + 紧邻空格」配对（如 案号|空|案由|空，标签也可能就在首格）
            pairs = {}
            for k, lc in enumerate(uniq):
                if k in consumed_cells:
                    continue
                lt = _clean("".join(p.text for p in lc.paragraphs))
                if (lt and len(lt) <= 12 and "□" not in lt and "：" not in lt
                        and k + 1 < len(uniq)):
                    nt = "".join(p.text for p in uniq[k + 1].paragraphs).strip()
                    if not nt:
                        pairs[k + 1] = lt
                        consumed_cells.add(k)
                        consumed_cells.add(k + 1)
            if 0 in consumed_cells:
                role = ""
            body = list(enumerate(uniq[1:], start=1))
            row_has_field = False
            pending_category = ""     # 如「民事类：」统领后续选项段
            opt_group = None          # 连续纯选项段合并组
            last_opt_field = None     # 行内最近的选项字段（用于 有/无 互补合并）

            def flush_group():
                nonlocal opt_group
                if not opt_group:
                    return
                opts, locs, style, name = opt_group
                # 去重保序
                seen, uopts = set(), []
                for o in opts:
                    o = o.rstrip("：:")
                    if o not in seen:
                        seen.add(o); uopts.append(o)
                ftype = "radio" if _is_radio(uopts) else "check"
                # 与行内上一选项字段互补（如有/无、是/否分处不同段落）则合并
                nonlocal last_opt_field
                if last_opt_field is not None:
                    union = set(last_opt_field["options"]) | set(uopts)
                    if (union <= _BINARY_WORDS and len(union) <= 4
                            and last_opt_field["loc"].get("style") == style):
                        for o in uopts:
                            if o not in last_opt_field["options"]:
                                last_opt_field["options"].append(o)
                        last_opt_field["loc"]["locs"].extend(locs)
                        opt_group = None
                        return
                loc = {"t": ti, "r": ri, "style": style, "locs": locs}
                add(ftype, _field_label(role, name), uopts, loc)
                last_opt_field = fields[-1]
                row_has_field = True
                opt_group = None

            # 先落地配对字段
            for blank_ci in sorted(pairs):
                add("text", _field_label(role, pairs[blank_ci]), None,
                    {"t": ti, "r": ri, "c": blank_ci, "p": 0, "empty": True})
                row_has_field = True

            for bi, (ci, cell) in enumerate(body):
                if ci in consumed_cells:
                    continue
                paras = list(cell.paragraphs)
                cell_text = "".join(p.text for p in paras).strip()

                cell_has_marker = False
                for pi, para in enumerate(paras):
                    text = para.text
                    if not text.strip():
                        continue
                    style, opts = _option_style_and_opts(text)
                    first_pos = opts[0][1] if opts else len(text)
                    last_end = opts[-1][2] if opts else 0
                    # 选项之前的标签（如「性别：男□ 女□」中的性别）作为选项名
                    pre_labels = labels_in(text[:first_pos])
                    rest_labels = [(lb, s, e) for lb, s, e in labels_in(text)
                                   if s >= last_end - 1]
                    # 分类统领词
                    cat = [lb for lb, _s, _e in rest_labels
                           if lb.endswith("类") and not text[_e: _e + 4].strip()]
                    rest_labels = [x for x in rest_labels if x[0] not in cat]
                    if cat and not opts:
                        flush_group()
                        pending_category = cat[0]
                        continue

                    if opts:
                        opt_names = [o.rstrip("：:") for o, _s, _e in opts]
                        fill_after = rest_labels or _RE_DATE_RUN.search(text[last_end:])
                        if not fill_after:
                            # 纯选项段：并入连续组
                            name = pending_category or (pre_labels[-1][0] if pre_labels else role)
                            if pending_category:
                                pending_category = ""
                            if (opt_group and (opt_group[2] != style or opt_group[3] != name)):
                                flush_group()
                            if not opt_group:
                                opt_group = [list(opt_names), [{"c": ci, "p": pi}], style, name]
                            else:
                                opt_group[0].extend(opt_names)
                                opt_group[1].append({"c": ci, "p": pi})
                            cell_has_marker = True
                            continue
                        # 混合段：先结算连续组，本段选项独立成字段
                        flush_group()
                        name = pending_category or (pre_labels[-1][0] if pre_labels else role)
                        if pending_category:
                            pending_category = ""
                        ftype = "radio" if _is_radio(opt_names) else "check"
                        loc = {"t": ti, "r": ri, "style": style,
                               "locs": [{"c": ci, "p": pi}]}
                        add(ftype, _field_label(role, name), opt_names, loc)
                        last_opt_field = fields[-1]
                        cell_has_marker = row_has_field = True
                    else:
                        flush_group()

                    # 日期：锚点取其前方最近标签
                    dm = _RE_DATE_RUN.search(text)
                    fill_labels = rest_labels if opts else labels_in(text)
                    if dm:
                        anchor = ""
                        before = [lb for lb, ls, _e in fill_labels if ls < dm.start()]
                        if before:
                            anchor = before[-1]
                            fill_labels = [(lb, s, e) for lb, s, e in fill_labels if lb != anchor]
                        add("date", _field_label(role, anchor or "日期"), None,
                            {"t": ti, "r": ri, "c": ci, "p": pi, "anchor": anchor})
                        cell_has_marker = row_has_field = True
                    for lb, _s, _e in fill_labels:
                        add("text", _field_label(role, lb), None,
                            {"t": ti, "r": ri, "c": ci, "p": pi, "anchor": lb})
                        cell_has_marker = row_has_field = True
                flush_group()
                # 整格空白且未被配对消费 → 自由填写区
                if not cell_has_marker and not cell_text and role and ci not in consumed_cells:
                    add("textarea", role, None,
                        {"t": ti, "r": ri, "c": ci, "p": 0, "empty": True})
                    row_has_field = True
    return fields


def _generic_schema(doc, title: str, cause: str) -> dict:
    raw = _generic_fields(doc)
    sections, idx = [], {}
    for f in raw:
        sec_name = f.pop("_section", "基本信息")
        if sec_name not in idx:
            idx[sec_name] = {"title": sec_name, "fields": []}
            sections.append(idx[sec_name])
        idx[sec_name]["fields"].append({
            "key": f["key"], "label": f["label"], "type": f["type"],
            "options": f.get("options", []),
        })
    return {"cause": cause or "", "title": title, "sections": sections,
            "field_count": len(raw)}


def _set_paragraph_text(paragraph, value: str):
    """整段写入自由文本（用于空白单元格 textarea），保留段落首个 run 的格式。"""
    runs = paragraph.runs
    if runs:
        runs[0].text = value
        for r in runs[1:]:
            r.text = ""
    else:
        paragraph.add_run(value)


def _cell_at(doc, t, r, c):
    """定位去重后的第 c 个单元格。"""
    seen, uniq = set(), []
    for cc in doc.tables[t].rows[r].cells:
        if cc._tc not in seen:
            seen.add(cc._tc); uniq.append(cc)
    return uniq[c] if c < len(uniq) else None


def _fill_generic(doc, values: dict):
    """按 values 回填任意模板（字段由 _generic_fields 现算，key 与 schema 同源）。"""
    from datetime import datetime
    fields = _generic_fields(doc)
    for f in fields:
        val = values.get(f["key"])
        loc = f["loc"]
        try:
            if f["type"] in ("radio", "check"):
                selected = val if isinstance(val, list) else ([val] if val else [])
                style = loc.get("style")
                for one in loc.get("locs", []):
                    cell = _cell_at(doc, loc["t"], loc["r"], one["c"])
                    if cell is None:
                        continue
                    paras = list(cell.paragraphs)
                    if one["p"] >= len(paras):
                        continue
                    p = paras[one["p"]]
                    for opt in f["options"]:
                        mark = "☑" if opt in selected else "□"
                        if style == "prefix":
                            _replace_text_in_paragraph(
                                p, r"□(\s*)" + re.escape(opt),
                                lambda m, _mk=mark, _o=opt: f"{_mk}{m.group(1)}{_o}",
                                regex=True)
                        else:
                            _replace_text_in_paragraph(p, f"{opt}□", f"{opt}{mark}")
                continue

            cell = _cell_at(doc, loc["t"], loc["r"], loc["c"])
            if cell is None:
                continue
            paras = list(cell.paragraphs)
            if loc["p"] >= len(paras):
                continue
            p = paras[loc["p"]]

            if f["type"] == "textarea":
                if val:
                    _set_paragraph_text(p, str(val))
            elif f["type"] == "text":
                if not val:
                    continue
                if loc.get("empty"):
                    _set_paragraph_text(p, str(val))
                else:
                    anchor = loc.get("anchor") or ""
                    if anchor:
                        _replace_text_in_paragraph(
                            p, re.escape(anchor) + r"：[ \t　]*",
                            f"{anchor}：{val}  ", regex=True)
            elif f["type"] == "date":
                if not val:
                    continue
                try:
                    d = datetime.strptime(str(val)[:10], "%Y-%m-%d")
                    date_str = f"{d.year}年{d.month:02d}月{d.day:02d}日"
                    anchor = loc.get("anchor") or ""
                    done = False
                    if anchor:
                        m = re.search(re.escape(anchor) + r"：.*?(年\s+月\s+日)", p.text)
                        if m:
                            _replace_text_in_paragraph(
                                p, re.escape(m.group(1)), date_str, regex=True)
                            done = True
                    if not done:
                        _replace_text_in_paragraph(p, r"年\s+月\s+日", date_str, regex=True)
                except Exception:
                    continue
        except (KeyError, IndexError):
            continue


def form_schema(template_id: int) -> dict:
    """获取指定模板的要素式表单 schema（离婚用精修规则，其余通用扫描）。"""
    t = db.query_one("SELECT * FROM doc_templates WHERE id=?", (template_id,))
    if not t:
        raise FileNotFoundError("模板不存在")
    if t.get("cause") == "离婚纠纷" and t.get("kind") == "民事起诉状":
        return {**_lihun_schema(), "field_count": len(_LIHUN_FIELDS)}
    from docx import Document
    p = TPL_DIR / t["rel_path"]
    if not p.exists():
        raise FileNotFoundError("模板文件缺失：" + t["rel_path"])
    schema = _generic_schema(Document(p), t.get("name") or "", t.get("cause") or "")
    if not schema["sections"]:
        schema["note"] = "该模板为普通文本格式，未识别到要素表格，可使用「一键生成」"
    return schema


def generate_filled(template_id: int, values: dict, case_path: str) -> dict:
    """按表单值生成已填充的 Word 文书（离婚走精修规则，其余走通用回填）。"""
    from . import vault
    t = db.query_one("SELECT * FROM doc_templates WHERE id=?", (template_id,))
    if not t:
        raise FileNotFoundError("模板不存在")
    src = TPL_DIR / t["rel_path"]
    if not src.exists():
        raise FileNotFoundError("模板文件缺失：" + t["rel_path"])

    from docx import Document
    doc = Document(src)
    is_lihun = t.get("cause") == "离婚纠纷" and t.get("kind") == "民事起诉状"
    if is_lihun:
        _fill_lihun(doc, values or {})
        label = "民事起诉状（要素式）"
    else:
        _fill_generic(doc, values or {})
        label = f"{t.get('kind') or '文书'}（要素式）"

    fm, _ = vault.parse_frontmatter(vault.abs_path(case_path).read_text(encoding="utf-8"))
    client, cause = fm.get("客户", ""), fm.get("案由", "")
    seq = docgen.next_seq(case_path)
    filename = docgen.build_filename(seq, client, cause, label)
    case_dir = DOCX_DIR / docgen.safe_name(f"{client}{cause}")
    case_dir.mkdir(parents=True, exist_ok=True)
    out = case_dir / filename
    doc.save(out)

    rel_path = out.relative_to(VAULT_DIR).as_posix()
    digest = docgen.hash_file(out)
    db.execute(
        "INSERT INTO gen_docs(case_path,seq,doc_type,filename,rel_path,created,"
        "system_hash,disk_hash,sync_state,template_id) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (case_path, seq, label, filename, rel_path, db.now(), digest, digest,
         "一致", template_id))
    db.audit("要素式文书生成", f"{filename} <- {t['name']} ({case_path})")
    return {"filename": filename, "rel_path": rel_path, "seq": seq,
            "abs_path": str(out), "template": t["name"], "doc_type": label}


# 预留：通用模板字段自动抽取入口（当前仅做结构扫描）
def _extract_form_schema(doc) -> dict:
    """通用要素式模板字段扫描：识别带 □ 的选项与带 ： 的文本标签。"""
    sections = []
    for ti, tbl in enumerate(doc.tables):
        for ri, row in enumerate(tbl.rows):
            if len(row.cells) < 2:
                continue
            header = (row.cells[0].text or "").strip()
            body = (row.cells[1].text or "").strip()
            if not body:
                continue
            fields = []
            # 简单行级解析
            for line in body.splitlines():
                line = line.strip()
                if not line:
                    continue
                if "□" in line:
                    opts = [m.group(1) for m in re.finditer(r"([^/\s]+?)□", line)]
                    if opts:
                        label = line.split("：")[0] if "：" in line else header
                        fields.append({"label": label, "type": "radio", "options": opts})
                elif "：" in line:
                    label = line.split("：")[0]
                    fields.append({"label": label, "type": "text"})
            if fields:
                sections.append({"title": header or f"表格{ti+1}第{ri+1}行", "fields": fields})
    return {"title": "要素式表单（自动扫描）", "sections": sections}
