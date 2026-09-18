# -*- coding: utf-8 -*-
"""通过本地 API 造演示数据（仅用于功能介绍截图）。"""

import json
import sys
import urllib.request

BASE = "http://127.0.0.1:8765"
TOKEN = sys.argv[1] if len(sys.argv) > 1 else ""


def call(method, path, body=None):
    req = urllib.request.Request(BASE + path, method=method)
    req.add_header("X-Auth-Token", TOKEN)
    data = None
    if body is not None:
        req.add_header("Content-Type", "application/json")
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    try:
        with urllib.request.urlopen(req, data, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:  # noqa
        return {"ok": False, "err": str(e)}


log = []

# ---- 案件（客户档案自动建档） ----
CASES = [
    dict(client="宏图贸易有限公司", cause="买卖合同纠纷", case_type="买卖合同纠纷",
         court="杭州市中级人民法院", procedure="普通程序", stage="开庭审理",
         case_no="（2026）浙01民初3389号", opponent="宁波甬江物资有限公司",
         contact_date="2026-07-02", filing_date="2026-07-30", hearing_date="2026-09-19",
         fee_amount=88000, fee_method="分阶段支付", subject_amount=1280000,
         risk_level="高", priority="高", tags="买卖合同;货款"),
    dict(client="张伟", cause="劳动争议", case_type="劳动争议",
         court="杭州市西湖区人民法院", procedure="简易程序", stage="开庭审理",
         case_no="（2026）浙0106民初4521号", opponent="杭州启航网络科技有限公司",
         contact_date="2026-08-02", filing_date="2026-08-20", hearing_date="2026-09-24",
         fee_amount=12000, fee_method="一次性支付", subject_amount=96000,
         risk_level="中", priority="普通", tags="劳动争议;违法解除"),
    dict(client="李静", cause="离婚纠纷", case_type="婚姻家庭",
         court="杭州市拱墅区人民法院", procedure="普通程序", stage="审理前准备",
         case_no="（2026）浙0105民初2190号", opponent="王强",
         contact_date="2026-07-28", filing_date="2026-08-05",
         fee_amount=15000, fee_method="一次性支付", subject_amount=2360000,
         risk_level="中", priority="普通", tags="婚姻家庭;财产分割"),
    dict(client="陈国栋", cause="民间借贷纠纷", case_type="民间借贷",
         court="杭州市上城区人民法院", procedure="简易程序", stage="裁判",
         case_no="（2026）浙0102民初1876号", opponent="周小明",
         contact_date="2026-05-06", filing_date="2026-05-12", hearing_date="2026-06-30",
         judgment_date="2026-08-28", judgment_eff_date="2026-09-15",
         fee_amount=20000, fee_method="风险代理", subject_amount=450000,
         risk_level="低", priority="普通", tags="民间借贷;已胜诉"),
    dict(client="宏图贸易有限公司", cause="常年法律顾问服务", case_type="常年法律顾问",
         stage="日常咨询与合同审查", contact_date="2026-03-01",
         fee_amount=60000, fee_method="年度包干", subject_amount=0,
         risk_level="低", priority="普通", tags="非诉;法律顾问"),
    dict(client="李静", cause="股权代持协议审查", case_type="合同审查与起草",
         stage="起草/审查初稿", contact_date="2026-09-10",
         fee_amount=6000, fee_method="一次性支付", subject_amount=0,
         risk_level="低", priority="普通", tags="非诉;合同审查"),
]

for c in CASES:
    r = call("POST", "/api/cases", c)
    log.append(("case", c["client"], c["cause"], r.get("ok"), r.get("err") or r.get("msg") or ""))

# ---- 待办任务 ----
TASKS = [
    ("宏图贸易案：核对证据原件并按清单装订", "2026-09-18", "紧急", "待办"),
    ("张伟劳动争议案：起草庭审提纲与发问提纲", "2026-09-20", "高", "待办"),
    ("李静离婚案：调取不动产登记与银行流水", "2026-09-22", "普通", "待办"),
    ("三季度创收对账与发票核销", "2026-09-25", "普通", "事务"),
]
for t, due, lv, kind in TASKS:
    r = call("POST", "/api/tasks", {"title": t, "due": due, "level": lv, "kind": kind})
    log.append(("task", t, r.get("ok"), ""))

# ---- 笔记（双链示范） ----
NOTES = [
    ("办案指引", "劳动争议办案清单",
     "## 庭审前核对\n- 劳动合同、工资流水、考勤记录\n- 违法解除的书面通知与送达证据\n\n"
     "## 常用条文\n- 《劳动合同法》第39、40、47、87条\n- [[案件/张伟-劳动争议]]\n"
     "相关案件：[[案件/宏图贸易有限公司-买卖合同纠纷]]"),
    ("办案指引", "证据交接规范",
     "1. 原件当面清点，出具《证据清单》双签\n2. 复印件标注「与原件核对一致」\n"
     "3. 扫描件归入 [[档案库]] 对应客户目录\n4. 庭后三日内归还原件并签收"),
    ("团队", "九月工作安排",
     "- 9月19日 宏图贸易开庭（中院）\n- 9月24日 张伟劳动争议开庭\n"
     "- 月底前完成三季度创收对账\n- 关联：[[案件/李静-离婚纠纷]]"),
]
for folder, title, body in NOTES:
    r = call("POST", "/api/note/create", {"folder": folder, "title": title, "body": body})
    log.append(("note", title, r.get("ok"), r.get("msg") or ""))

# ---- 计时记录 ----
TIMERS = [
    ("案件/宏图贸易有限公司-买卖合同纠纷", "证据梳理与质证意见", 5400, 800),
    ("案件/张伟-劳动争议", "庭审提纲起草", 3600, 800),
    ("案件/李静-离婚纠纷", "财产线索梳理", 4500, 800),
]
for cp, title, sec, rate in TIMERS:
    r = call("POST", "/api/timer", {"case_path": cp, "title": title, "seconds": sec,
                                    "rate": rate, "billable": 1,
                                    "started": "2026-09-16 09:30:00",
                                    "ended": "2026-09-16 11:00:00"})
    log.append(("timer", title, r.get("ok"), ""))

for row in log:
    print(row)
print("DONE")
