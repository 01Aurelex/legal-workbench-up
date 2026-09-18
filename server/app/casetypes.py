# -*- coding: utf-8 -*-
"""案件类型与流程模板。

- 诉讼/仲裁/执行：沿用民商事流程引擎（民诉法期限倒排）。
- 非诉业务：采用"阶段制"流程模板，不套用审限，按锚点日期 + 建议周期倒排节点。
- 全部数据驱动：用户可在设置中新增、重命名、停用自定义类型，内置类型不可删除。
"""
from __future__ import annotations
from datetime import datetime, date, timedelta

from . import db

DATE_FMT = "%Y-%m-%d"

# ---------------- 非诉流程模板 ----------------
# stage: (阶段名, 距上一阶段建议天数, 交付物, 要点)
NONLIT_FLOWS: dict[str, dict] = {
    "nonlit_retainer": {
        "label": "常年法律顾问",
        "stages": [
            ("签约与建档", 0, ["常年法律顾问合同", "授权委托书"], "统一收案、利益冲突审查、明确服务范围与响应时限。"),
            ("走访与法律体检", 14, ["法律体检报告", "风险清单"], "梳理公司治理、合同、劳动人事、知识产权等条线现状。"),
            ("制度与模板搭建", 45, ["制度汇编", "常用合同模板"], "输出可落地的制度与模板包，完成培训交底。"),
            ("日常咨询与合同审查", 90, ["审查意见", "咨询回复记录"], "按服务响应时限处理，留存工作底稿与工时记录。"),
            ("风险预警与专项", 180, ["专项法律意见书", "风险提示函"], "对重大事项出具专项意见，主动提示合规风险。"),
            ("年度总结与续约", 365, ["年度服务报告", "续约协议"], "汇总服务成果、工时与价值，推进续约。"),
        ],
    },
    "nonlit_contract": {
        "label": "合同审查与起草",
        "stages": [
            ("需求沟通与资料收集", 0, ["需求确认单", "背景资料"], "明确交易结构、商业目标、风险偏好与不可让步条款。"),
            ("起草/审查初稿", 3, ["合同初稿", "审查意见表"], "先结构后条款，重点审查主体、标的、价款、违约、争议解决。"),
            ("内部复核", 5, ["复核记录"], "二级复核并留痕，重大合同需合伙人复核。"),
            ("与客户确认修改", 8, ["修改说明"], "逐条说明修改理由与风险点，标注谈判优先级。"),
            ("定稿交付", 12, ["合同定稿", "交付清单"], "交付可签署版本并留存终稿与版本记录。"),
        ],
    },
    "nonlit_corporate": {
        "label": "公司设立与变更",
        "stages": [
            ("方案设计与材料清单", 0, ["设立方案", "材料清单"], "确定组织形式、注册资本、股权比例与经营范围。"),
            ("名称核准/材料制备", 5, ["名称核准通知书", "章程草案"], "准备章程、股东协议、任职文件等。"),
            ("提交登记", 10, ["登记申请材料"], "线上或现场提交，跟进补正。"),
            ("领取执照与刻章", 15, ["营业执照", "印章"], "领取营业执照、刻制印章、银行开户。"),
            ("税务与后置许可", 20, ["税务登记", "许可证"], "完成税务报到、票种核定及行业许可。"),
        ],
    },
    "nonlit_ma": {
        "label": "投融资与并购",
        "stages": [
            ("交易结构与路径设计", 0, ["交易方案", "时间表"], "明确交易模式、对价、支付方式与时间表。"),
            ("尽职调查", 15, ["尽调清单", "尽调报告"], "法律、财务、业务三线尽调，输出重大问题清单。"),
            ("交易文件起草", 30, ["股权转让/增资协议", "股东协议"], "先决条件、陈述保证、违约与退出机制。"),
            ("谈判与定稿", 45, ["谈判纪要", "文件定稿"], "就核心商业条款与风险分配达成一致。"),
            ("签署与交割", 60, ["签署页", "交割确认书"], "签署、履行先决条件、完成交割。"),
            ("交割后事项与工商变更", 75, ["工商变更登记", "交割后清单"], "工商变更、备案与后续整改跟踪。"),
        ],
    },
    "nonlit_dd": {
        "label": "尽职调查",
        "stages": [
            ("尽调方案与清单", 0, ["尽调方案", "资料清单"], "明确范围、口径与分工。"),
            ("资料收集与核验", 7, ["资料台账", "访谈提纲"], "原件核对、访谈留痕。"),
            ("问题梳理与风险评估", 14, ["问题清单", "风险矩阵"], "按重大/一般分级，提出解决建议。"),
            ("出具尽调报告", 21, ["尽调报告"], "结论先行，附证据与建议。"),
        ],
    },
    "nonlit_hr": {
        "label": "劳动人事合规",
        "stages": [
            ("用工现状摸底", 0, ["用工台账", "风险清单"], "梳理劳动合同、社保、工时、加班与派遣用工。"),
            ("制度起草与修订", 15, ["员工手册", "规章制度"], "民主程序与公示留痕，确保可执行。"),
            ("文本与流程落地", 30, ["合同模板", "流程表单"], "入转调离全流程文本配套。"),
            ("培训与答疑", 45, ["培训材料", "答疑记录"], "对 HR 与管理者开展培训。"),
        ],
    },
    "nonlit_opinion": {
        "label": "法律意见书",
        "stages": [
            ("明确问题与范围", 0, ["问题清单", "范围说明"], "限定意见所依据的事实与假设前提。"),
            ("法律检索与论证", 7, ["检索报告", "法规汇编"], "检索现行有效法规、案例与监管口径。"),
            ("内部复核", 12, ["复核意见"], "结论与依据交叉验证。"),
            ("出具正式意见书", 15, ["法律意见书"], "明确免责与用途限制条款。"),
        ],
    },
    "nonlit_letter": {
        "label": "律师函/催告函",
        "stages": [
            ("事实核实与授权", 0, ["授权委托书", "证据材料"], "核实事实与证据，取得客户书面授权。"),
            ("起草与审核", 2, ["律师函初稿"], "措辞严谨、请求明确、留有余地。"),
            ("签发与寄送", 3, ["签发记录", "快递单号"], "EMS 寄送并留存回执与内容副本。"),
            ("结果跟进", 10, ["回函记录", "跟进方案"], "跟踪对方回应，评估是否进入诉讼。"),
        ],
    },
    "nonlit_ip": {
        "label": "知识产权布局",
        "stages": [
            ("现状盘点与布局规划", 0, ["IP 清单", "布局方案"], "梳理商标、专利、著作权、商业秘密。"),
            ("申请文件准备", 15, ["申请文件"], "类别选择、权利要求与说明书撰写。"),
            ("提交申请", 25, ["受理通知书"], "提交并跟踪受理。"),
            ("审查答复", 120, ["答复意见", "补正材料"], "答复审查意见或补正。"),
            ("授权与维护", 300, ["权利证书", "年费提醒"], "授权后维护与年费监控。"),
        ],
    },
    "nonlit_compliance": {
        "label": "合规体系建设",
        "stages": [
            ("合规风险识别", 0, ["风险库", "合规义务清单"], "识别外部义务与内部风险。"),
            ("制度与流程设计", 30, ["合规手册", "流程文件"], "设计三道防线与运行机制。"),
            ("落地实施与培训", 60, ["培训记录", "承诺书"], "全员宣贯与签署承诺。"),
            ("运行评价与改进", 120, ["评价报告", "整改清单"], "年度评价并持续改进。"),
        ],
    },
}

# 未单独定义模板的非诉类型统一走通用流程
NONLIT_GENERIC = {
    "label": "非诉通用流程",
    "stages": [
        ("需求沟通与立项", 0, ["需求确认单", "利益冲突检索记录"], "明确目标、范围、交付成果与时间表，完成收案与冲突审查。"),
        ("尽职调查/资料收集", 7, ["资料清单", "尽调报告"], "收集并核验基础材料，识别关键风险。"),
        ("方案设计与论证", 15, ["方案建议书", "法律检索报告"], "比较可选路径，给出推荐方案与依据。"),
        ("文件起草", 25, ["法律文件初稿"], "按方案起草交易文件/制度文本。"),
        ("内部复核", 30, ["复核记录"], "二级复核并留痕，重大事项合伙人复核。"),
        ("交付与签署", 35, ["定稿文件", "交付清单"], "向客户交付定稿，协助签署并留存原件。"),
        ("履行跟进与归档", 60, ["履行台账", "结案归档清单"], "跟踪履行情况，完成结案归档与评价。"),
    ],
}


def flow_of(flow_key: str) -> dict:
    return NONLIT_FLOWS.get(flow_key, NONLIT_GENERIC)


# ---------------- 类型管理 ----------------
def list_types(include_disabled: bool = True) -> list[dict]:
    sql = "SELECT * FROM case_types"
    if not include_disabled:
        sql += " WHERE enabled=1"
    sql += " ORDER BY sort, id"
    return db.query(sql)


def grouped() -> dict:
    out: dict[str, list[dict]] = {}
    for t in list_types(False):
        out.setdefault(t["category"], []).append(t)
    return out


def add_type(name: str, category: str = "自定义", flow: str = "nonlit_generic") -> dict:
    name = (name or "").strip()
    if not name:
        raise ValueError("类型名称不能为空")
    if db.query_one("SELECT id FROM case_types WHERE name=?", (name,)):
        raise ValueError("该类型已存在")
    mx = db.query_one("SELECT COALESCE(MAX(sort),0) m FROM case_types")["m"]
    tid = db.insert("case_types", {"name": name, "category": category, "flow": flow,
                                   "builtin": 0, "enabled": 1, "sort": mx + 1,
                                   "created": db.now()})
    db.audit("新增案件类型", f"{name}（{category}）")
    return db.query_one("SELECT * FROM case_types WHERE id=?", (tid,))


def update_type(tid: int, patch: dict) -> dict:
    row = db.query_one("SELECT * FROM case_types WHERE id=?", (tid,))
    if not row:
        raise ValueError("类型不存在")
    name = (patch.get("name") or row["name"]).strip()
    if name != row["name"] and db.query_one("SELECT id FROM case_types WHERE name=? AND id!=?", (name, tid)):
        raise ValueError("该类型名称已存在")
    db.execute("UPDATE case_types SET name=?, category=?, flow=?, enabled=?, sort=? WHERE id=?",
               (name, patch.get("category", row["category"]), patch.get("flow", row["flow"]),
                int(patch.get("enabled", row["enabled"])), int(patch.get("sort", row["sort"])), tid))
    return db.query_one("SELECT * FROM case_types WHERE id=?", (tid,))


def delete_type(tid: int) -> dict:
    row = db.query_one("SELECT * FROM case_types WHERE id=?", (tid,))
    if not row:
        raise ValueError("类型不存在")
    if row["builtin"]:
        raise ValueError("内置类型不可删除，可选择停用")
    db.execute("DELETE FROM case_types WHERE id=?", (tid,))
    db.audit("删除案件类型", row["name"])
    return {"ok": True, "name": row["name"]}


def reorder(ids: list[int]) -> dict:
    for i, tid in enumerate(ids):
        db.execute("UPDATE case_types SET sort=? WHERE id=?", (i, int(tid)))
    return {"ok": True}


def flow_preview(flow_key: str) -> list[dict]:
    f = flow_of(flow_key)
    offset = 0
    out = []
    for name, gap, deliverables, note in f["stages"]:
        offset += gap
        out.append({"name": name, "offset_days": offset,
                    "deliverables": deliverables, "note": note})
    return out


# ---------------- 非诉时间轴计算 ----------------
def _d(s: str):
    s = (s or "").strip()
    if not s:
        return None
    try:
        return datetime.strptime(s[:10], DATE_FMT).date()
    except Exception:
        return None


def nonlit_timeline(case: dict) -> list[dict]:
    """非诉案件按"启动日 + 阶段建议周期"倒排节点；已完成的阶段按当前阶段判定。"""
    flow_key = case.get("flow") or "nonlit_generic"
    f = flow_of(flow_key)
    anchor = _d(case.get("contact_date") or case.get("filing_date") or "")
    stage = (case.get("stage") or "").strip()
    stage_names = [s[0] for s in f["stages"]]
    cur_idx = stage_names.index(stage) if stage in stage_names else 0
    today = date.today()
    offset = 0
    out = []
    for i, (name, gap, deliverables, note) in enumerate(f["stages"]):
        offset += gap
        item = {"key": f"nl_{i}", "name": name, "anchor": "contact_date",
                "basis": f"非诉流程模板《{f['label']}》", "deliverables": deliverables,
                "note": note, "offset_days": offset}
        if anchor is None:
            item["due"] = ""
            item["status"] = "未触发"
        else:
            due = anchor + timedelta(days=offset)
            item["due"] = due.strftime(DATE_FMT)
            delta = (due - today).days
            if i < cur_idx:
                item["status"] = "已完成"
            elif i == cur_idx:
                item["status"] = "进行中"
            elif delta < 0:
                item["status"] = f"已逾期{-delta}天"
            elif delta <= 3:
                item["status"] = f"临近（剩{delta}天）"
            else:
                item["status"] = f"待办（剩{delta}天）"
        out.append(item)
    return out


def stage_options(flow_key: str) -> list[str]:
    return [s[0] for s in flow_of(flow_key)["stages"]]
