# -*- coding: utf-8 -*-
"""案件一键导入：扫描本地文件夹，调用本地 AI 分析归类，并入案件 / 客户管理系统。

流程分两步（与前端「预览 → 手动调整 → 确认导入」对应）：
1. scan(folder)：递归扫描并分类，返回可编辑的「分组预览」，**不写入任何文件**；
2. commit(folder, groups, move)：按用户确认/调整后的分组，建客户档案、建案件、归档文件。

AI 不可用时自动降级为本地关键词启发式分类，用户仍可在预览中修正。
"""
from __future__ import annotations
import json
import re
import shutil
from pathlib import Path

from .config import VAULT_DIR
from . import db, vault, archive, casetypes, workflow, ai_hub

# 案件类型 → 关键词（与前端 cases.js 的 TYPE_ALIASES 对齐，用于无 AI 时的启发式归类）
TYPE_KEYWORDS: dict[str, list[str]] = {
    "婚姻家庭": ["离婚", "结婚", "夫妻", "抚养", "扶养", "赡养", "收养", "彩礼", "同居", "探望", "监护", "家暴"],
    "继承纠纷": ["继承", "遗嘱", "遗产", "遗赠", "法定继承"],
    "劳动争议": ["劳动", "工伤", "辞退", "解雇", "工资", "加班", "竞业", "社保", "确认劳动关系", "经济补偿"],
    "合同纠纷": ["合同", "违约", "承揽", "委托", "定金"],
    "买卖合同纠纷": ["买卖", "货款", "供货", "购销", "订单"],
    "民间借贷": ["借款", "借条", "欠条", "利息", "欠钱", "借贷"],
    "金融借款": ["信用卡", "银行贷款", "金融借款", "逾期贷款"],
    "侵权责任纠纷": ["侵权", "损害", "交通事故", "受伤", "打架", "医疗事故", "名誉", "隐私", "产品责任"],
    "房屋买卖/租赁": ["房屋", "买房", "卖房", "租房", "租赁", "商品房", "物业", "业主", "相邻"],
    "建设工程": ["工程", "施工", "工程款", "包工头", "分包"],
    "公司股权纠纷": ["公司", "股权", "股东", "出资", "分红", "知情权"],
    "知识产权": ["商标", "专利", "著作权", "版权", "商业秘密", "不正当竞争"],
    "票据纠纷": ["票据", "汇票", "支票", "本票"],
    "破产重整": ["破产", "重整", "债权人会议"],
    "仲裁案件": ["仲裁", "仲裁委"],
    "执行案件": ["执行", "强制执行", "查封", "失信"],
    "刑事辩护": ["刑事", "诈骗", "盗窃", "故意伤害", "危险驾驶", "取保"],
    "行政诉讼": ["行政", "行政处罚", "行政复议", "强拆", "政府信息公开"],
    "常年法律顾问": ["法律顾问", "常年顾问", "常法"],
    "合同审查与起草": ["合同审查", "审查合同", "起草合同", "合同起草"],
    "公司设立与变更": ["设立公司", "注册公司", "工商变更", "公司变更"],
    "股权架构设计": ["股权架构", "股权设计", "持股平台"],
    "投融资并购": ["并购", "投融资", "收购", "重组并购"],
    "尽职调查": ["尽职调查", "尽调", "法律尽调"],
    "增资扩股": ["增资", "扩股", "融资入股"],
    "改制重组": ["改制", "国企改革", "企业重组"],
    "劳动人事合规": ["用工合规", "人事合规", "员工手册", "规章制度合规"],
    "规章制度制定": ["规章制度", "员工制度", "制度制定"],
    "知识产权布局": ["知识产权布局", "专利布局", "商标布局"],
    "商标/专利申请": ["商标申请", "专利申请", "注册商标", "申请专利"],
    "税务筹划": ["税务", "税收筹划", "节税"],
    "法律意见书": ["法律意见", "意见书", "专项意见"],
    "律师函/催告函": ["律师函", "催告函", "催款函", "警告函"],
    "谈判与调解": ["谈判", "调解", "和解谈判"],
    "发债与上市": ["上市", "发债", "IPO", "债券发行"],
    "私募基金": ["私募基金", "基金备案", "募投"],
    "破产清算（管理人）": ["破产清算", "清算", "管理人"],
    "合规体系建设": ["合规体系", "合规建设", "反垄断合规"],
    "数据合规与个人信息保护": ["数据合规", "个人信息保护", "数据安全", "个保法"],
    "涉外法律服务": ["涉外", "跨境", "外资", "英文合同"],
    "公证与见证": ["公证", "见证", "律师见证"],
    "法律培训": ["培训", "法律讲座", "普法"],
    "家族财富管理": ["家族财富", "财富传承", "家族信托"],
}

_TRAIL = re.compile(r"(纠纷|争议|案件|诉讼|仲裁|协议|合同|委托|顾问|服务)$")


def _safe_name(name: str) -> str:
    return "".join(c for c in (name or "未命名") if c not in '\\/:*?"<>|').strip() or "未命名"


def _dedup_target(target: Path) -> Path:
    if not target.exists():
        return target
    stem, ext, n = target.stem, target.suffix, 1
    while True:
        cand = target.with_name(f"{stem}_{n}{ext}")
        if not cand.exists():
            return cand
        n += 1


def _read_sample(path: Path, limit: int = 500) -> str:
    """读取少量文本内容用于 AI/启发式分析（docx/pdf/md/txt），图片等跳过。"""
    ext = path.suffix.lower()
    try:
        if ext in (".md", ".txt", ".markdown"):
            for enc in ("utf-8", "gb18030"):
                try:
                    return path.read_text(encoding=enc)[:limit]
                except UnicodeDecodeError:
                    continue
            return ""
        if ext == ".docx":
            import docx
            d = docx.Document(str(path))
            paras = [p.text.strip() for p in d.paragraphs if p.text.strip()]
            return "\n".join(paras)[:limit]
        if ext == ".pdf":
            import pypdf
            reader = pypdf.PdfReader(str(path))
            text = "\n".join((pg.extract_text() or "") for pg in reader.pages[:2])
            return text.strip()[:limit]
    except Exception:
        return ""
    return ""


def _all_types() -> list[dict]:
    return db.query("SELECT name,category,flow FROM case_types WHERE enabled=1 ORDER BY sort,id")


def _heuristic(text: str, types: list[dict]) -> dict:
    """无 AI 时的关键词启发式归类。"""
    best, best_score = None, 0
    for t in types:
        score = 0
        if t["name"] and t["name"] in text:
            score += 4
        for k in TYPE_KEYWORDS.get(t["name"], []):
            if k and k in text:
                score += 1 + (1 if len(k) >= 3 else 0)
        if score > best_score:
            best, best_score = t, score
    if not best:
        best = {"name": "", "category": "诉讼仲裁", "flow": "civil_flow"}
    return {"case_type": best["name"], "case_category": best["category"] or "诉讼仲裁",
            "flow": best["flow"] or "civil_flow"}


def _infer_client(source_name: str, case_type: str) -> str:
    """从文件夹名粗略推断客户名（用户可在预览中修正）。"""
    s = (source_name or "").strip()
    for token in [case_type] + TYPE_KEYWORDS.get(case_type, []):
        if token:
            s = s.replace(token, " ")
    s = re.sub(r"[_\-—·、]+", " ", s)
    s = _TRAIL.sub("", s.strip())
    s = re.sub(r"\s+", " ", s).strip(" -—_·")
    # 去掉常见量词/残留符号
    s = re.sub(r"^(的|与|和|及)\s*", "", s)
    return s or (source_name or "未命名客户").strip()


def _ai_classify(text: str, types: list[dict], timeout: float = 20.0) -> dict | None:
    """调用本地 AI 做结构化归类，失败返回 None（由调用方降级启发式）。"""
    try:
        if not ai_hub.status().get("reachable"):
            return None
    except Exception:
        return None
    type_names = [t["name"] for t in types if t["name"]]
    sys = (
        "你是律师工作台的文件归档助手。请分析给定案件资料的内容，只输出一个 JSON 对象，"
        "不要输出任何其它文字、注释或代码块标记。JSON 字段："
        '{"client":"客户名称","cause":"案由","case_type":"案件类型","category":"诉讼仲裁或非诉业务或自定义","opponent":"对方当事人(可空)"}。\n'
        "要求：client 从文件夹/文件名中提取自然人或企业名称，提取不到就用文件夹名；"
        "case_type 必须从下面列表选最接近的一个；category 与所选 case_type 业务类别一致；"
        "cause 用简短案由短语。\n\n案件类型列表：" + "、".join(type_names)
    )
    q = "请分析并归类以下案件资料内容：\n\n" + text[:2000]
    r = ai_hub.one_shot(q, sys, timeout=timeout)
    if not r.get("ok") or not r.get("text"):
        return None
    raw = r["text"].strip()
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except Exception:
        return None
    name = (obj.get("case_type") or "").strip()
    type_map = {t["name"]: t for t in types}
    t = type_map.get(name)
    return {
        "client": (obj.get("client") or "").strip(),
        "cause": (obj.get("cause") or name).strip(),
        "case_type": name,
        "case_category": (t["category"] if t else (obj.get("category") or "诉讼仲裁")),
        "opponent": (obj.get("opponent") or "").strip(),
    }


def _classify(text: str, source_name: str, types: list[dict]) -> dict:
    """AI 优先，失败降级启发式。返回 {client,cause,case_type,case_category,opponent,ai}。"""
    ai = _ai_classify(text, types)
    if ai and ai.get("client"):
        return {**ai, "ai": True}
    h = _heuristic(text, types)
    return {"client": _infer_client(source_name, h["case_type"]),
            "cause": h["case_type"] or "未分类",
            "case_type": h["case_type"], "case_category": h["case_category"],
            "opponent": "", "ai": False}


def scan(folder: str) -> dict:
    """扫描文件夹并返回可编辑的分组预览（不写文件）。"""
    root = Path(folder).expanduser()
    if not root.exists() or not root.is_dir():
        raise ValueError("文件夹不存在或不是目录")
    root_res = root.resolve()
    if root_res == VAULT_DIR.resolve() or VAULT_DIR.resolve() in root_res.parents:
        raise ValueError("不能导入档案库自身目录，请选择其他文件夹")

    types = _all_types()
    existing_clients = {c["client"] for c in db.query(
        "SELECT DISTINCT client FROM cases WHERE client!=''")}
    existing_cases = {Path(c["rel_path"]).stem for c in db.query("SELECT rel_path FROM cases")}

    # 分组：按顶层子目录；根目录下散落的文件归入「(根目录)」组
    groups_map: dict[str, dict] = {}
    total = 0
    for f in sorted(root.rglob("*")):
        if not f.is_file() or f.name.startswith("."):
            continue
        ext = f.suffix.lower()
        if ext not in archive.SCAN_EXT:
            continue
        total += 1
        rel_sub = f.relative_to(root).as_posix()
        base = rel_sub.split("/", 1)[0] if "/" in rel_sub else ""
        key = base or "__root__"
        g = groups_map.setdefault(key, {"base": base, "source_name": base or root.name,
                                        "files": [], "_paths": []})
        g["files"].append({"name": f.name, "rel": rel_sub, "size": f.stat().st_size, "ext": ext})
        g["_paths"].append(f)

    # 构建上下文并分类（每组读取自己文件的内容采样，供 AI/启发式分析）
    groups = []
    for key in sorted(groups_map.keys()):
        g = groups_map[key]
        names = " ".join(x["name"] for x in g["files"][:20])
        sample = ""
        for p in g["_paths"]:
            if p.suffix.lower() in (".md", ".txt", ".docx", ".pdf"):
                sample = _read_sample(p)
                if sample:
                    break
        text = f"{g['source_name']} {names}\n{sample}"
        cls = _classify(text, g["source_name"], types)
        groups.append({
            "key": key, "base": g["base"], "source_name": g["source_name"],
            "file_count": len(g["files"]), "files": g["files"][:200],
            "client": cls["client"], "cause": cls["cause"],
            "case_type": cls["case_type"], "case_category": cls["case_category"],
            "opponent": cls["opponent"], "ai": cls["ai"],
            "existing_client": cls["client"] in existing_clients,
            "existing_case": f"{cls['client']}-{cls['cause']}" in existing_cases,
        })

    ai_reachable = False
    try:
        ai_reachable = bool(ai_hub.status().get("reachable"))
    except Exception:
        ai_reachable = False
    return {"ok": True, "source": str(root), "total": total, "ai_available": ai_reachable,
            "groups": groups}


def _ensure_client(name: str, extra: dict | None = None) -> str:
    """客户档案：不存在则自动建档，已存在则原样保留（不覆盖用户已录信息）。"""
    name = (name or "").strip()
    rel_path = f"客户/{name}.md"
    if not (VAULT_DIR / rel_path).exists():
        e = extra or {}
        fm = {"type": "client", "标题": name, "联系方式": e.get("contact", ""),
              "身份证/统一信用代码": e.get("idno", ""), "对方当事人": e.get("opponent", ""),
              "地址": e.get("address", ""), "备注": "案件一键导入时自动建档",
              "最近联系": db.today()}
        body = (f"# {name}\n\n## 基本信息\n- 联系方式：{e.get('contact','')}\n"
                f"- 证件号码：{e.get('idno','')}\n- 地址：{e.get('address','')}\n"
                f"- 对方当事人：{e.get('opponent','')}\n\n## 关联案件\n\n## 沟通记录\n")
        vault.write_note(rel_path, vault.dump_frontmatter(fm, body))
    return rel_path


def _create_case(client: str, cause: str, case_type: str, category: str, opponent: str) -> str:
    """创建案件笔记并写入结构化索引（已存在则不重复创建）。"""
    name = f"{client}-{cause}"
    rel_path = f"案件/{name}.md"
    if (VAULT_DIR / rel_path).exists():
        return rel_path

    t = db.query_one("SELECT * FROM case_types WHERE name=?", (case_type,)) if case_type else None
    flow = (t["flow"] if t else "civil_flow")
    stage = casetypes.stage_options(flow)[0] if flow.startswith("nonlit") else "委托"

    fm = {"type": "case", "标题": name, "客户": client,
          "客户链接": f"[[客户/{client}]]", "案由": cause,
          "案件类型": case_type, "业务类别": category,
          "管辖法院": "", "程序": "普通程序", "阶段": stage, "案号": "",
          "对方当事人": opponent, "委托日期": db.today(),
          "立案日期": "", "开庭日期": "", "判决日期": "", "裁判类型": "判决",
          "生效日期": "", "律师费": 0, "收费方式": "", "标的额": 0,
          "风险等级": "中", "优先级": "普通", "标签": "一键导入"}
    body = (f"# {name}\n\n## 案件概要\n- 客户：[[客户/{client}]]\n- 案件类型：{case_type}（{category}）\n"
            f"- 案由：{cause}\n- 对方当事人：{opponent}\n\n"
            f"## 事实经过\n\n## 诉讼请求/服务目标\n\n## 证据目录\n\n## 办案日志\n")
    vault.write_note(rel_path, vault.dump_frontmatter(fm, body))

    db.execute("UPDATE cases SET case_type=?, case_category=?, contact_date=?, opponent=?, "
               "tags=? WHERE rel_path=?",
               (case_type, category, db.today(), opponent, "一键导入", rel_path))
    # 客户笔记回链
    cp = VAULT_DIR / f"客户/{client}.md"
    if cp.exists():
        txt = cp.read_text(encoding="utf-8")
        if f"[[案件/{name}]]" not in txt:
            cp.write_text(txt.rstrip() + f"\n- [[案件/{name}]]\n", encoding="utf-8")
    return rel_path


def commit(folder: str, groups: list[dict], move: bool = False) -> dict:
    """按用户确认/调整后的分组，建客户、建案件、归档文件。"""
    root = Path(folder).expanduser()
    if not root.exists() or not root.is_dir():
        raise ValueError("文件夹不存在或不是目录")
    root_res = root.resolve()
    if root_res == VAULT_DIR.resolve() or VAULT_DIR.resolve() in root_res.parents:
        raise ValueError("不能导入档案库自身目录，请选择其他文件夹")

    # 重建 base -> files 映射
    base_files: dict[str, list[Path]] = {}
    for f in sorted(root.rglob("*")):
        if not f.is_file() or f.name.startswith("."):
            continue
        if f.suffix.lower() not in archive.SCAN_EXT:
            continue
        rel_sub = f.relative_to(root).as_posix()
        base = rel_sub.split("/", 1)[0] if "/" in rel_sub else ""
        base_files.setdefault(base or "__root__", []).append(f)

    created_cases, created_clients, archived, skipped = 0, 0, 0, 0
    for g in groups or []:
        key = g.get("base") or "__root__"
        client = (g.get("client") or "").strip()
        cause = (g.get("cause") or "").strip()
        if not client or not cause:
            skipped += 1
            continue
        files = base_files.get(key, [])
        if not files:
            skipped += 1
            continue
        # 建客户（已存在则不覆盖）
        cp = VAULT_DIR / f"客户/{client}.md"
        if not cp.exists():
            _ensure_client(client, {"opponent": g.get("opponent", "")})
            created_clients += 1
        # 建案件
        case_name = f"{client}-{cause}"
        rel_path = f"案件/{case_name}.md"
        if not (VAULT_DIR / rel_path).exists():
            _create_case(client, cause, g.get("case_type", ""),
                         g.get("case_category", "诉讼仲裁"), g.get("opponent", ""))
            created_cases += 1
        # 归档文件 → 材料/<客户-案由>/<相对子路径>
        base_dir = g.get("base") or ""
        for f in files:
            rel_sub = f.relative_to(root).as_posix()
            if base_dir:
                sub = rel_sub[len(base_dir):].lstrip("/")
            else:
                sub = rel_sub
            dest_dir = VAULT_DIR / "材料" / _safe_name(case_name)
            if sub:
                dest_dir = dest_dir / Path(sub).parent
            dest_dir.mkdir(parents=True, exist_ok=True)
            target = _dedup_target(dest_dir / _safe_name(f.name))
            try:
                if move:
                    shutil.move(str(f), str(target))
                else:
                    shutil.copy2(str(f), str(target))
                archived += 1
            except Exception:
                continue

    vault.scan_vault()
    workflow.rebuild_case_reminders()
    archive.sync_registry()
    db.audit("案件一键导入", f"{root} → 建案{created_cases} 建档{created_clients} 归档{archived} 跳过{skipped}")
    return {"ok": True, "source": str(root), "created_cases": created_cases,
            "created_clients": created_clients, "archived": archived, "skipped": skipped,
            "moved": bool(move)}
