# -*- coding: utf-8 -*-
"""民商事案件流程引擎。
期限规则全部依据《中华人民共和国民事诉讼法》(2023修正)、民诉法解释(2022修正)、
《民事诉讼证据若干规定》(2019修正)、《律师法》(2017修正) 现行条文，条文原文随本地法律库分发。
"""
from __future__ import annotations
from datetime import datetime, date, timedelta

from . import db, casetypes

DATE_FMT = "%Y-%m-%d"

def _d(s: str):
    s = (s or "").strip()
    if not s:
        return None
    try:
        return datetime.strptime(s[:10], DATE_FMT).date()
    except Exception:
        return None

def _add(d: date, days: int) -> str:
    return (d + timedelta(days=days)).strftime(DATE_FMT)

# 程序 -> 一审审限天数
TRIAL_LIMIT = {"普通程序": 183, "简易程序": 92, "小额诉讼": 61}   # 六个月≈183日 / 三个月≈92日 / 两个月≈61日
EVIDENCE_LIMIT = {"普通程序": 15, "简易程序": 15, "小额诉讼": 7}  # 普通≥15日；简易≤15；小额一般≤7

# 一审流程节点（anchor=案件上的锚点日期字段，offset=锚点之后第 N 日到期/应完成）
FIRST_INSTANCE = [
    {"key": "entrust", "name": "建立委托关系", "anchor": "contact_date", "offset": 0,
     "basis": "《律师法》第25条；《律师事务所管理办法》第46条",
     "deliverables": ["法律服务合同", "授权委托书", "委托人风险告知书", "利益冲突检索记录", "委托人身份证明留存"],
     "note": "由律所统一接受委托、签订书面委托合同、统一收费并进行利益冲突审查。"},
    {"key": "file_case", "name": "提交立案材料", "anchor": "filing_date", "offset": 0,
     "basis": "《民事诉讼法》第122-124条",
     "deliverables": ["民事起诉状", "原告主体资格证明", "证据清单", "授权委托书", "律师事务所函", "送达地址确认书"],
     "note": "起诉须符合第122条四项条件；起诉状按被告人数提交副本（第123条），记明事项见第124条。"},
    {"key": "accept", "name": "法院立案审查结果", "anchor": "filing_date", "offset": 7,
     "basis": "《民事诉讼法》第126条",
     "deliverables": ["受理案件通知书(取得)"],
     "note": "符合起诉条件的，法院应在七日内立案并通知；不符合的七日内裁定不予受理。"},
    {"key": "defense", "name": "被告答辩期届满", "anchor": "filing_date", "offset": 20,
     "basis": "《民事诉讼法》第128条",
     "deliverables": ["答辩状(代理被告时)"],
     "note": "法院立案之日起5日内发送起诉状副本，被告收到之日起15日内提出答辩状（按立案起算约20日，实际以送达回证为准）。"},
    {"key": "evidence", "name": "举证期限届满", "anchor": "filing_date", "offset": 15,
     "basis": "民诉法解释第99条；《民事诉讼证据若干规定》第51条",
     "deliverables": ["证据材料", "证据清单", "证人出庭申请书(如需)"],
     "note": "普通程序法院指定举证期限不得少于15日；简易程序不得超过15日；小额诉讼一般不超过7日，以法院《举证通知书》为准。"},
    {"key": "hearing_notice", "name": "开庭通知/传票核对", "anchor": "hearing_date", "offset": -3,
     "basis": "《民事诉讼法》第139条",
     "deliverables": ["传票(取得)", "出庭准备清单", "代理词/质证意见"],
     "note": "法院应在开庭三日前通知当事人和其他诉讼参与人；收到传票后立即核对并倒排准备。"},
    {"key": "hearing", "name": "开庭审理", "anchor": "hearing_date", "offset": 0,
     "basis": "《民事诉讼法》第十二章第三节",
     "deliverables": ["庭审笔录(核对)", "代理词"],
     "note": "参加庭审、举证质证、法庭辩论，核对庭审笔录后签字。"},
    {"key": "trial_limit", "name": "一审审限届满", "anchor": "filing_date", "offset": 183,
     "basis": "《民事诉讼法》第152条/第164条/第168条",
     "deliverables": ["判决书/裁定书/调解书(取得)"],
     "note": "普通程序立案之日起六个月内审结（可依法延长）；简易程序三个月；小额诉讼两个月。"},
    {"key": "appeal", "name": "上诉期届满", "anchor": "judgment_date", "offset": 15,
     "basis": "《民事诉讼法》第171条",
     "deliverables": ["上诉状(如需)"],
     "note": "不服一审判决的，判决书送达之日起十五日内上诉；不服裁定的，十日内上诉。期限为不变期间，务必以送达回证日期起算。"},
    {"key": "enforce", "name": "申请执行期间届满", "anchor": "judgment_eff_date", "offset": 730,
     "basis": "《民事诉讼法》第250条",
     "deliverables": ["申请执行书", "生效法律文书副本", "申请执行人身份证明", "被执行人财产线索"],
     "note": "申请执行期间为二年，自法律文书规定履行期间最后一日起算；可因中止、中断重新计算。"},
]

STAGE_ORDER = ["委托", "立案", "审理前准备", "开庭审理", "裁判", "二审", "执行", "结案"]


# ---------------- 刑事流程（刑事诉讼法 2018 修正） ----------------
# anchor=案件锚点日期字段；offset=锚点之后第 N 日到期/应完成
CRIMINAL_FLOW = [
    {"key": "entrust", "name": "建立委托关系", "anchor": "contact_date", "offset": 0,
     "basis": "《律师法》第25条；《刑事诉讼法》第34条",
     "deliverables": ["委托书", "会见笔录", "风险告知书"],
     "note": "犯罪嫌疑人自第一次讯问或采取强制措施之日起有权委托辩护人，侦查阶段只能委托律师。"},
    {"key": "detain", "name": "拘留后提请批准逮捕", "anchor": "filing_date", "offset": 3,
     "basis": "《刑事诉讼法》第91条",
     "deliverables": ["提请批准逮捕书(了解)", "取保候审申请(如需)"],
     "note": "拘留后一般3日内提请批捕，特殊情况可延长至4日；流窜/多次/结伙作案可延长至30日。"},
    {"key": "arrest_review", "name": "检察院审查批捕", "anchor": "filing_date", "offset": 7,
     "basis": "《刑事诉讼法》第91条",
     "deliverables": ["批捕决定(了解)", "羁押必要性审查申请(如需)"],
     "note": "检察院自接到提请批准逮捕书后7日内作出是否批准逮捕决定。"},
    {"key": "investigation", "name": "侦查羁押期限届满", "anchor": "filing_date", "offset": 61,
     "basis": "《刑事诉讼法》第156-158条",
     "deliverables": ["侦查期限跟踪表"],
     "note": "一般侦查羁押期限不超过2个月；案情复杂可经上一级检察院批准延长1个月等，注意依法延长。"},
    {"key": "prosecute", "name": "审查起诉期限届满", "anchor": "filing_date", "offset": 91,
     "basis": "《刑事诉讼法》第172条",
     "deliverables": ["辩护意见", "不起诉意见(如需)"],
     "note": "检察院应在1个月内作出决定，重大复杂可延长15日；认罪认罚符合速裁的10日内决定。"},
    {"key": "hearing_notice", "name": "开庭通知核对", "anchor": "hearing_date", "offset": -3,
     "basis": "《刑事诉讼法》第186条",
     "deliverables": ["开庭通知(取得)", "辩护意见/质证提纲"],
     "note": "开庭3日以前送达传票与通知书，收到后立即核对并倒排准备。"},
    {"key": "hearing", "name": "开庭审理", "anchor": "hearing_date", "offset": 0,
     "basis": "《刑事诉讼法》第三编第二章",
     "deliverables": ["庭审笔录(核对)", "辩护词"],
     "note": "参加庭审、质证辩论，核对庭审笔录后签字。"},
    {"key": "trial_limit", "name": "一审审限届满", "anchor": "hearing_date", "offset": 61,
     "basis": "《刑事诉讼法》第208条",
     "deliverables": ["判决书(取得)"],
     "note": "一审公诉案件受理后2个月内宣判，至迟不超过3个月；简易程序20日、速裁程序10-15日。"},
    {"key": "appeal", "name": "上诉期届满", "anchor": "judgment_date", "offset": 10,
     "basis": "《刑事诉讼法》第230条",
     "deliverables": ["上诉状(如需)"],
     "note": "不服判决上诉期10日，不服裁定5日，自收到裁判文书次日起算。"},
    {"key": "second_trial", "name": "二审审限届满", "anchor": "judgment_date", "offset": 71,
     "basis": "《刑事诉讼法》第243条",
     "deliverables": ["二审裁判文书(取得)"],
     "note": "二审受理后2个月内审结，特殊可延长。"},
]

# ---------------- 行政流程（行政诉讼法 2017 修正） ----------------
ADMIN_FLOW = [
    {"key": "entrust", "name": "建立委托关系", "anchor": "contact_date", "offset": 0,
     "basis": "《律师法》第25条；《行政诉讼法》第31条",
     "deliverables": ["委托书", "风险告知书"],
     "note": "当事人可委托律师、基层法律服务工作者等作为诉讼代理人。"},
    {"key": "sue", "name": "起诉期限届满", "anchor": "filing_date", "offset": 180,
     "basis": "《行政诉讼法》第46条",
     "deliverables": ["行政起诉状", "证据清单"],
     "note": "知道或应当知道作出行政行为之日起6个月内提起诉讼；经复议的收到复议决定书后15日内。"},
    {"key": "accept", "name": "法院立案审查", "anchor": "filing_date", "offset": 7,
     "basis": "《行政诉讼法》第51条",
     "deliverables": ["受理通知书(取得)"],
     "note": "法院应在7日内决定是否立案；不符合的裁定不予立案。"},
    {"key": "hearing_notice", "name": "开庭通知核对", "anchor": "hearing_date", "offset": -3,
     "basis": "《行政诉讼法》第67条",
     "deliverables": ["开庭通知(取得)", "代理意见/质证意见"],
     "note": "收到开庭传票后立即核对并倒排准备。"},
    {"key": "hearing", "name": "开庭审理", "anchor": "hearing_date", "offset": 0,
     "basis": "《行政诉讼法》第七章",
     "deliverables": ["庭审笔录(核对)", "代理词"],
     "note": "参加庭审，对行政行为合法性进行举证质证。"},
    {"key": "trial_limit", "name": "一审审限届满", "anchor": "filing_date", "offset": 183,
     "basis": "《行政诉讼法》第81条",
     "deliverables": ["判决书(取得)"],
     "note": "一审立案之日起6个月内作出判决。"},
    {"key": "appeal", "name": "上诉期届满", "anchor": "judgment_date", "offset": 15,
     "basis": "《行政诉讼法》第85条",
     "deliverables": ["上诉状(如需)"],
     "note": "不服判决15日内上诉，不服裁定10日内上诉。"},
    {"key": "second_trial", "name": "二审审限届满", "anchor": "judgment_date", "offset": 105,
     "basis": "《行政诉讼法》第88条",
     "deliverables": ["二审裁判文书(取得)"],
     "note": "二审立案之日起3个月内作出终审裁判。"},
]


def compute_timeline(case: dict) -> list[dict]:
    """根据案件锚点日期计算各节点到期日与状态（民商事/执行，依据民诉法）。"""
    proc = case.get("procedure") or "普通程序"
    today = date.today()
    out = []
    for rule in FIRST_INSTANCE:
        anchor_key = rule["anchor"]
        anchor_val = case.get(anchor_key) or ""
        if rule["key"] == "evidence":
            offset = EVIDENCE_LIMIT.get(proc, 15)
        elif rule["key"] == "trial_limit":
            offset = TRIAL_LIMIT.get(proc, 183)
        elif rule["key"] == "appeal" and case.get("judgment_type") == "裁定":
            offset = 10
        else:
            offset = rule["offset"]
        item = dict(rule)
        item["anchor_date"] = anchor_val
        anchor = _d(anchor_val)
        if anchor is None:
            item["due"] = ""
            item["status"] = "未触发"
        else:
            due = anchor + timedelta(days=offset)
            item["due"] = due.strftime(DATE_FMT)
            delta = (due - today).days
            if item["key"] in ("hearing", "file_case", "entrust") and delta < 0:
                item["status"] = "已完成/已发生"
            elif delta < 0:
                item["status"] = f"已逾期{-delta}天"
            elif delta <= 3:
                item["status"] = f"临近（剩{delta}天）"
            else:
                item["status"] = f"待办（剩{delta}天）"
        out.append(item)
    return out


def _fixed_flow_timeline(case: dict, rules: list[dict]) -> list[dict]:
    """按固定 offset 的流程规则倒排（刑事/行政，不按程序类型覆盖）。"""
    today = date.today()
    out = []
    for rule in rules:
        item = dict(rule)
        anchor_val = case.get(rule["anchor"]) or ""
        item["anchor_date"] = anchor_val
        anchor = _d(anchor_val)
        if anchor is None:
            item["due"] = ""
            item["status"] = "未触发"
        else:
            due = anchor + timedelta(days=rule["offset"])
            item["due"] = due.strftime(DATE_FMT)
            delta = (due - today).days
            if item["key"] in ("hearing", "entrust") and delta < 0:
                item["status"] = "已完成/已发生"
            elif delta < 0:
                item["status"] = f"已逾期{-delta}天"
            elif delta <= 3:
                item["status"] = f"临近（剩{delta}天）"
            else:
                item["status"] = f"待办（剩{delta}天）"
        out.append(item)
    return out


# ---------- 文件清单智能匹配（委托/诉讼全流程） ----------
CHECKLIST = [
    ("委托", "法律服务合同", "《律师法》第25条：律所统一接受委托、签订书面委托合同、统一收费"),
    ("委托", "授权委托书", "《民事诉讼法》第61条；委托他人代为诉讼须提交授权委托书，记明事项与权限"),
    ("委托", "委托人风险告知书", "执业规范：告知诉讼风险、举证责任与费用"),
    ("委托", "利益冲突检索记录", "《律师事务所管理办法》第46条：受理前进行利益冲突审查"),
    ("委托", "委托人身份证明留存", "自然人身份证/法人营业执照与法定代表人身份证明"),
    ("委托", "收费凭证", "《律师法》第25条：统一收取费用、如实入账并出具有效凭证"),
    ("立案", "民事起诉状", "《民事诉讼法》第123、124条：按被告人数提交副本，记明法定事项"),
    ("立案", "原告主体资格证明", "原告为公民/法人或其他组织的身份证明材料"),
    ("立案", "证据清单", "编号、证据名称、页数、证明对象、来源"),
    ("立案", "证据材料", "按对方当事人人数+法院份数准备复印件"),
    ("立案", "律师事务所函", "律师代理诉讼时向法院出具的所函"),
    ("立案", "送达地址确认书", "确认送达地址与联系方式"),
    ("审理前准备", "答辩状", "《民事诉讼法》第128条：被告收到起诉状副本之日起15日内"),
    ("审理前准备", "质证意见", "围绕证据真实性、合法性、关联性准备"),
    ("审理前准备", "管辖异议申请书", "提交答辩状期间提出（如需要）"),
    ("审理前准备", "调查取证/保全申请书", "举证期限届满前提出（如需要）"),
    ("开庭审理", "代理词", "庭审发表/庭后提交的代理意见"),
    ("开庭审理", "庭审笔录", "当庭核对并签字确认"),
    ("裁判", "上诉状", "《民事诉讼法》第171条：判决15日/裁定10日"),
    ("执行", "申请执行书", "《民事诉讼法》第250条：二年申请执行时效"),
    ("执行", "生效法律文书副本", "判决书/裁定书/调解书及生效证明"),
    ("执行", "被执行人财产线索", "银行账户、不动产、股权、车辆等"),
]


def nonlit_checklist(case: dict) -> list[dict]:
    """非诉业务：按流程模板的交付物生成文件清单（不套用民诉法）。"""
    flow_key = case.get("flow") or "nonlit_generic"
    f = casetypes.flow_of(flow_key)
    stage = (case.get("stage") or "").strip()
    stage_names = [s[0] for s in f["stages"]]
    cur = stage_names.index(stage) if stage in stage_names else 0
    items = []
    for i, (name, gap, deliverables, note) in enumerate(f["stages"]):
        for d in deliverables:
            items.append({
                "stage": name, "doc_type": d, "basis": f"非诉流程《{f['label']}》·{name}",
                "need_level": "必备" if i <= cur + 1 else "后续预备",
                "generated": False, "note": note,
            })
    return items


def match_checklist(case: dict, generated_types: set[str]) -> list[dict]:
    # 非诉业务走流程模板清单
    if case.get("case_category") == "非诉业务" or (case.get("flow") or "").startswith("nonlit"):
        items = nonlit_checklist(case)
        for it in items:
            it["generated"] = it["doc_type"] in generated_types
        return items
    stage = case.get("stage") or "立案"
    order = STAGE_ORDER
    cur = order.index(stage) if stage in order else 1
    items = []
    for st, doc_type, basis in CHECKLIST:
        idx = STAGE_ORDER.index(st) if st in STAGE_ORDER else 99
        # 委托+当前阶段及之前的阶段为"必备"，之后为"后续可能需要"
        need_level = "必备" if idx <= max(cur, 1) else "后续预备"
        items.append({
            "stage": st, "doc_type": doc_type, "basis": basis,
            "need_level": need_level,
            "generated": doc_type in generated_types,
        })
    return items


def timeline_for(case: dict) -> list[dict]:
    """按案件类别自动分派：民商事走民诉法、刑事走刑诉法、行政走行诉法、非诉走阶段模板。

    关键：绝不把非诉/刑事/行政案件套用民诉法审限。"""
    flow = (case.get("flow") or "").strip()
    category = case.get("case_category") or ""
    if category == "非诉业务" or flow.startswith("nonlit"):
        return casetypes.nonlit_timeline(case)
    if flow == "criminal":
        return _fixed_flow_timeline(case, CRIMINAL_FLOW)
    if flow == "administrative":
        return _fixed_flow_timeline(case, ADMIN_FLOW)
    if flow == "arbitration":
        return casetypes.nonlit_timeline({**case, "flow": "nonlit_generic"})
    # civil_flow / enforcement / 未指定：走民商事流程引擎（含执行）
    return compute_timeline(case)


# ---------------- 案由 / 案件类型 AI 把关 ----------------
# 诉讼类案由常见词（用于规则兜底，判断案由是否明显指向诉讼/争议）
LITIGATION_MARKERS = ["纠纷", "诉讼", "争议", "赔偿", "违约", "侵权", "离婚", "继承",
                      "劳动争议", "借款", "追偿", "确认", "返还", "排除妨害", "物权",
                      "合同", "票据", "破产", "仲裁", "执行"]
NONLIT_MARKERS = ["顾问", "审查", "起草", "尽调", "尽职调查", "合规", "意见书", "律师函",
                  "催告", "谈判", "调解", "公证", "见证", "培训", "架构", "股权激励",
                  "融资", "并购", "上市", "发债", "私募", "清算", "登记", "备案", "年检"]

TIMELINE_KIND = {
    "civil_flow": "民商事诉讼流程（民诉法审限）",
    "enforcement": "执行流程（民诉法执行编）",
    "criminal": "刑事流程（刑诉法期限）",
    "administrative": "行政流程（行诉法期限）",
    "arbitration": "仲裁流程",
}


def cause_guard(case_type: str, cause: str, category: str = "") -> dict:
    """案由把关：依据案件类型与案由关键词，判断类别是否一致，给出提示。

    规则兜底 + 供 AI 增强；保证「非诉业务绝不算诉讼审限、刑事行政各归其位」。"""
    from . import db as _db
    cause = (cause or "").strip()
    t = _db.query_one("SELECT * FROM case_types WHERE name=?", (case_type,)) if case_type else None
    cat = (t["category"] if t else (category or ""))
    flow = (t["flow"] if t else "civil_flow")
    kind = TIMELINE_KIND.get(flow, "非诉阶段流程（不计算诉讼审限）" if flow.startswith("nonlit") else flow)

    warnings = []
    lit_hit = any(m in cause for m in LITIGATION_MARKERS)
    nonlit_hit = any(m in cause for m in NONLIT_MARKERS)

    if flow.startswith("nonlit") or cat == "非诉业务":
        if lit_hit and not nonlit_hit and case_type not in ("律师函/催告函", "谈判与调解"):
            warnings.append("案由含诉讼争议字眼，但案件类型为非诉业务——将按非诉阶段流程管理，不计算诉讼审限。如确属诉讼，请改选「诉讼仲裁」类案件类型。")
    else:
        if nonlit_hit and not lit_hit:
            warnings.append("案由更像非诉/专项事务，但案件类型为诉讼——将按诉讼审限倒排。如属非诉，请改选「非诉业务」类类型。")

    return {"category": cat, "flow": flow, "timeline_kind": kind,
            "consistent": not warnings, "warnings": warnings}


def rebuild_case_reminders() -> int:
    """扫描全部案件，重建期限提醒（幂等）。"""
    db.execute("DELETE FROM reminders WHERE kind='期限'")
    n = 0
    for c in db.query("SELECT * FROM cases"):
        for item in timeline_for(c):
            if not item.get("due"):
                continue
            st = item.get("status") or ""
            if st.startswith("未触发") or st.startswith("已完成"):
                continue
            level = "高" if ("逾期" in st or "临近" in st) else "普通"
            db.execute(
                "INSERT INTO reminders(kind,title,detail,due,level,ref,created) VALUES(?,?,?,?,?,?,?)",
                ("期限", f"{c.get('client','')}-{c.get('cause','')}：{item['name']}",
                 f"{item['basis']}；{item['note']}", item["due"], level, c["rel_path"], db.now()))
            n += 1
    return n
