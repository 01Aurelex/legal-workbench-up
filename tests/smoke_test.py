# -*- coding: utf-8 -*-
"""预览版功能可行性 + 安全防护自测脚本（仅访问 127.0.0.1 本机服务）。"""
import json, re, sys, urllib.request, urllib.error, urllib.parse, os
import http.client
from pathlib import Path

BASE = "http://127.0.0.1:8765"
PASS, FAIL = [], []

# 被测服务的数据根目录：
#   1) run_smoke.py 通过 LW_SMOKE_ROOT 传入（推荐，支持 --root build/src）；
#   2) 否则取当前工作目录，若其下没有 data/ 再往上一级找（历史发行版布局）。
_SMOKE_ROOT = Path(os.environ.get("LW_SMOKE_ROOT") or os.getcwd())
if not (_SMOKE_ROOT / "data").is_dir() and (_SMOKE_ROOT.parent / "data").is_dir():
    _SMOKE_ROOT = _SMOKE_ROOT.parent
DATA = _SMOKE_ROOT / "data"

def call(method, path, body=None, headers=None, raw_host=None, expect_status=200):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    hh = {"Content-Type": "application/json; charset=utf-8"}
    for k, v in (headers or {}).items():
        hh[k] = v
    conn = http.client.HTTPConnection("127.0.0.1", 8765, timeout=15)
    if raw_host:
        hh["Host"] = raw_host
    try:
        conn.request(method, path, body=data, headers=hh)
        r = conn.getresponse()
        raw = r.read().decode("utf-8")
        try:
            return r.status, json.loads(raw)
        except Exception:
            return r.status, {}
    except Exception as e:
        return -1, {"error": str(e)}
    finally:
        conn.close()

def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")

# 1 引导令牌
st, d = call("GET", "/api/bootstrap")
token = d.get("token", "")
H = {"X-Auth-Token": token}
check("本机引导获取令牌", len(token) >= 32)

# 2 无令牌必须 401
st, _ = call("GET", "/api/vault/tree")
check("无令牌访问被拒(401)", st == 401, f"status={st}")

# 3 伪造 Host 必须 403（DNS-rebind 防护）
st, _ = call("GET", "/api/vault/tree", headers={"X-Auth-Token": token}, raw_host="evil.example.com")
check("非法Host被拒(403)", st == 403, f"status={st}")

# 4 扫描
st, d = call("POST", "/api/vault/scan", headers=H)
check("档案库扫描", d.get("ok"), str(d.get("stat")))

# 5 客户/案件
st, d = call("POST", "/api/clients", {"name": "张先生", "contact": "138****0000"}, H)
st, d = call("POST", "/api/cases", {"client": "张先生", "cause": "劳动争议",
            "court": "惠州市惠城区人民法院", "procedure": "简易程序", "stage": "委托",
            "contact_date": "2026-09-01", "filing_date": "2026-09-01"}, H)
case_path = d.get("path") or "案件/张先生-劳动争议.md"
check("创建案件", bool(case_path), case_path)

# 6 案件详情：时间轴
st, d = call("GET", f"/api/case/detail?path={urllib.parse.quote(case_path)}", headers=H)
tl = d.get("timeline", [])
check("时间轴节点数>=10", len(tl) >= 10, f"n={len(tl)}")
due_map = {t["key"]: t["due"] for t in tl}
# 2026-09-01 立案：7日内立案结果=09-08；简易举证期限15日=09-16；3个月审限=12-02(近似)
check("立案审查7日(民诉法126条)", due_map.get("accept") == "2026-09-08", due_map.get("accept"))
check("简易程序举证期限15日(证据规定51条)", due_map.get("evidence") == "2026-09-16", due_map.get("evidence"))
check("简易程序3个月审限(民诉法164条)", due_map.get("trial_limit") == "2026-12-02", due_map.get("trial_limit"))
check("文件清单覆盖委托+诉讼阶段", len(d.get("checklist", [])) >= 20, f"n={len(d.get('checklist', []))}")

# 7 一键生成全部必备文书（先清理本案例历史生成记录，保证测试可重复）
import sqlite3, shutil
_db = DATA / "workbench.sqlite3"
if _db.exists():
    con = sqlite3.connect(str(_db))
    con.execute("DELETE FROM gen_docs WHERE case_path=?", (case_path,))
    con.commit(); con.close()
_gen_dir = DATA / "vault" / "文书" / "张先生劳动争议"
if _gen_dir.is_dir():
    shutil.rmtree(_gen_dir, ignore_errors=True)
st, d = call("POST", "/api/case/gen-all", {"case_path": case_path}, H)
made = d.get("made", [])
names = [m["filename"] for m in made]
check("批量生成空白文书", len(made) >= 6, f"共{len(made)}份")
expect_re = r"^00张先生劳动争议法律服务合同" + __import__("datetime").date.today().strftime("%Y%m%d") + r"\.docx$"
first = names[0] if names else ""
check("命名规则=序号+客户+案由+类型+日期", bool(re.match(expect_re, first)), first)
check("序号递增(第二份为01开头)", bool(names[1].startswith("01")) if len(names) > 1 else False, names[1] if len(names)>1 else "")
for m in made:
    check(f"文件落盘:{m['filename']}", (DATA / "vault" / m["rel_path"]).exists())

# 8 双链/图谱/反向链接
st, d = call("GET", "/api/graph", headers=H)
check("关系图谱节点>=2、边>=1", len(d.get("nodes", [])) >= 2 and len(d.get("edges", [])) >= 1,
      f"nodes={len(d.get('nodes',[]))} edges={len(d.get('edges',[]))}")
st, d = call("GET", f"/api/backlinks?path={urllib.parse.quote('客户/张先生.md')}", headers=H)
bl = d.get("backlinks", [])
check("客户笔记存在案件反向链接", len(bl) >= 1, str([x['rel_path'] for x in bl]))

# 9 AI 严格依据本地法律库（无本地模型时为纯检索演示模式）
st, d = call("POST", "/api/ai/ask", {"question": "简易程序的举证期限最长多少天？"}, H)
ev = d.get("evidence", [])
check("AI检索到本地法律库依据", len(ev) >= 1, d.get("mode"))
check("AI引用证据规定/民诉法解释", any("举证期限" in e["text"] and "十五" in e["text"] for e in ev))
st2, d2 = call("POST", "/api/ai/ask", {"question": "火星移民适用什么法律？"}, H)
check("库外问题不编造(无依据/明示)", d2.get("mode") == "无依据" or "未检索到" in d2.get("answer", ""), d2.get("mode"))

# 10 法律库状态与版本检测
st, d = call("GET", "/api/lawlib/status", headers=H)
check("本地法律库已索引(>=3文件,>=20条文块)", d.get("law_files", 0) >= 3 and d.get("chunks", 0) >= 20,
      f"files={d.get('law_files')} chunks={d.get('chunks')}")
st, d = call("GET", "/api/ai/version-check", headers=H)
check("模型版本检测给出推荐/提示", len(d.get("recommended", [])) >= 3 and len(d.get("hints", [])) >= 1)

# 11 外部修改文书 -> 系统检测 -> 同步
st, d = call("GET", "/api/sync/pending", headers=H)
docs = d.get("docs", [])
check("初始状态无待同步", all(x["sync_state"] == "一致" for x in docs) or docs == [])
# 找到第一份 docx，追加字节模拟外部修改
st, det = call("GET", f"/api/case/detail?path={urllib.parse.quote(case_path)}", headers=H)
relp = det["docs"][0]["rel_path"]
_cand = DATA / "vault" / relp
if _cand.exists():
    with open(_cand, "ab") as f:
        f.write(b"\n<!-- external edit -->")
st, d = call("GET", "/api/sync/pending", headers=H)
pend = [x for x in d.get("docs", []) if x["sync_state"] == "外部已修改"]
check("外部改动被检测并提示", len(pend) >= 1)
if pend:
    st, d = call("POST", "/api/sync/accept", {"id": pend[0]["id"]}, H)
    check("用户确认后系统记录同步", d.get("ok"))

# 12 飞书未配置时不外发
st, d = call("POST", "/api/feishu/sync", {"path": relp}, H)
check("飞书未配置时零外发并保留本地", d.get("ok") is False and "本地" in d.get("error", ""), d.get("error"))

# 13 能力探测
st, d = call("GET", "/api/media/caps", headers=H)
check("多模态能力探测返回", "caps" in d and "docx" in d["caps"] and d["caps"]["docx"]["available"])

# 14 第二轮新增：微信无服务器方案
st, d = call("GET", "/api/wechat/status", headers=H)
check("微信状态返回三通道字段", d.get("send_mode") in ("kf", "template", "subscribe") and "无需公网" in d.get("note", ""))
st, d = call("POST", "/api/wechat/test-send", {"content": "test"}, H)
check("未启用微信时测试发送安全失败(零外发)", d.get("ok") is False)
# 设置可保存新字段并回读
st, _ = call("POST", "/api/settings", {"wechat": {"enabled": False, "send_mode": "template",
             "template_id": "TPL_X", "default_openid": "oTest", "sandbox": True}}, H)
st, d = call("GET", "/api/settings", headers=H)
# 未激活状态下该接口会被授权门禁拦下（403，无 settings 字段），用 .get 兜底避免测试自身崩溃
w = (d.get("settings") or {}).get("wechat") or {}
check("微信新设置字段持久化", w.get("send_mode") == "template" and w.get("template_id") == "TPL_X"
      and w.get("default_openid") == "oTest" and w.get("sandbox") is True, str(w) or str(d)[:200])
# 还原默认，避免污染
call("POST", "/api/settings", {"wechat": {"enabled": False, "send_mode": "kf",
     "template_id": "", "default_openid": "", "sandbox": False}}, H)

# 15 第二轮新增：法律库清单 + 全文条文数量
st, d = call("GET", "/api/lawlib/list", headers=H)
names = [f["name"] for f in d.get("files", [])]
check("法律库含三部全文", any("民事诉讼法" in n for n in names) and any("律师法" in n for n in names)
      and any("劳动争议调解仲裁法" in n for n in names), str(names))

# 16 第二轮新增：OCR 端到端（生成含中文的图片走 /api/media/ocr）
# --skip-ocr 或 LW_SMOKE_SKIP_OCR=1：CI 环境未安装 OCR 引擎 / 缺中文字体时跳过该项，
# 避免把"环境缺失"误报成"功能回归"。
if os.environ.get("LW_SMOKE_SKIP_OCR") == "1" or "--skip-ocr" in sys.argv:
    print("[SKIP] 本地OCR端到端识别中文（--skip-ocr）")
else:
  try:
    from PIL import Image, ImageDraw, ImageFont
    import io, uuid
    im = Image.new("RGB", (560, 100), "white")
    dr = ImageDraw.Draw(im)
    try:
        fnt = ImageFont.truetype(r"C:\Windows\Fonts\simsun.ttc", 36)
    except Exception:
        fnt = ImageFont.load_default()
    dr.text((15, 25), "举证期限十五日", font=fnt, fill="black")
    buf = io.BytesIO(); im.save(buf, format="PNG")
    boundary = "----lw" + uuid.uuid4().hex
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"t.png\"\r\n"
            "Content-Type: image/png\r\n\r\n").encode() + buf.getvalue() + f"\r\n--{boundary}--\r\n".encode()
    conn = http.client.HTTPConnection("127.0.0.1", 8765, timeout=60)
    conn.request("POST", "/api/media/ocr", body=body,
                 headers={"X-Auth-Token": token, "Content-Type": f"multipart/form-data; boundary={boundary}"})
    r = conn.getresponse(); ocr = json.loads(r.read().decode()); conn.close()
    check("本地OCR端到端识别中文", ocr.get("ok") and "举证期限" in ocr.get("text", ""),
          f"{ocr.get('engine')}: {ocr.get('text','')[:40]}")
  except Exception as e:
    check("本地OCR端到端识别中文", False, f"测试异常:{e}")

print("\n========== 测试汇总 ==========")
print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
if FAIL:
    print("失败项：", FAIL); sys.exit(1)
print("全部通过")
