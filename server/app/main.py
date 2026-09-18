# -*- coding: utf-8 -*-
"""律师本地工作台 · 后端主程序（FastAPI，仅绑定 127.0.0.1）。

模块：档案库（双链 + 多维表格 + 本地打开）/ 案件 / 客户 / 创收 / 发票 / 日程 /
      计时 / 通讯录 / AI 对话 / 提醒 / 飞书多维表格同步 / 设置。
"""
from __future__ import annotations
import contextlib
import json
import time
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse

from .config import (BASE_DIR, VAULT_DIR, LAWLIB_DIR, FRONTEND_DIR, DATA_DIR,
                     load_config, save_config, AUDIT_PATH)
from . import (db, vault, workflow, docgen, lawlib, llm, watcher, archive,
               casetypes, revenue, invoice, bitable, ai_hub, stats, scheduler,
               media, mail, case_import, doctpl, intake, license as lic, llm_runtime)
from . import integrations_feishu as feishu
from . import integrations_wechat as wechat
from .security import get_or_create_token, security_middleware, SECRETS


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI):
    db.init_db()
    doctpl.sync_templates()
    vault.scan_vault()
    lawlib.build_index()
    archive.sync_registry()
    revenue.sync_all_case_fees()
    workflow.rebuild_case_reminders()
    watcher.start()
    scheduler.start()
    # 内置本地大模型后台预热（不阻塞启动；无内置模型时静默跳过）
    import threading
    threading.Thread(target=llm_runtime.ensure_running, daemon=True).start()
    db.audit("系统启动", "本地工作台启动")
    yield
    llm_runtime.stop()


app = FastAPI(title="法岩律师工作台", docs_url=None, redoc_url=None, lifespan=lifespan)
app.middleware("http")(security_middleware)


@app.middleware("http")
async def no_cache_frontend(request: Request, call_next):
    """前端为无构建 ESM，禁止浏览器缓存旧模块（避免更新后仍运行旧代码的假故障）。"""
    resp = await call_next(request)
    if not request.url.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store, must-revalidate"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
    return resp


@app.middleware("http")
async def license_gate(request: Request, call_next):
    """未激活仅开放案件管理：其余 API 一律 403 锁定（激活后全放行）。"""
    path = request.url.path
    if path.startswith("/api/") and path != "/api/bootstrap":
        if not lic.api_allowed(path, request.method):
            st = lic.license_status()
            return JSONResponse({"ok": False, "locked": True,
                                 "error": "软件尚未激活，免费版仅可使用案件管理，激活后解锁全部功能"},
                                status_code=403)
    return await call_next(request)

FRONTEND = FRONTEND_DIR


def ok(**kw):
    return JSONResponse({"ok": True, **kw})


def fail(msg: str, code: int = 400):
    return JSONResponse({"ok": False, "error": msg}, status_code=code)


class _Json:
    """把 dict 伪装成 Request，便于内部复用处理函数。"""

    def __init__(self, d):
        self._d = d

    async def json(self):
        return self._d


def _flow_of_case(c: dict) -> dict:
    """补齐案件的 flow 字段（来自案件类型表），供流程引擎分派。"""
    if not c:
        return c
    if not (c.get("flow") or "").strip() and c.get("case_type"):
        t = db.query_one("SELECT flow,category FROM case_types WHERE name=?", (c["case_type"],))
        if t:
            c["flow"] = t["flow"] or ""
            c.setdefault("case_category", t["category"] or "")
    return c


def _case_rows_with_flow() -> list[dict]:
    types = {t["name"]: t for t in db.query("SELECT name,flow,category FROM case_types")}
    out = []
    for c in db.query("SELECT * FROM cases ORDER BY updated DESC"):
        t = types.get(c.get("case_type") or "")
        c["flow"] = (t["flow"] if t else "") or ""
        if t and not c.get("case_category"):
            c["case_category"] = t["category"] or ""
        out.append(c)
    return out


# ==================== 引导 / 健康检查 ====================
@app.get("/api/bootstrap")
async def bootstrap(request: Request):
    ip = request.client.host if request.client else ""
    if ip not in ("127.0.0.1", "::1"):
        return fail("仅本机可引导", 403)
    return ok(token=get_or_create_token(), license=lic.license_status())


# ==================== 授权激活（一机一码） ====================
@app.get("/api/license/status")
async def license_status():
    return ok(**lic.license_status())


@app.post("/api/license/activate")
async def license_activate(request: Request):
    d = await request.json()
    code = (d.get("code") or "").strip()
    if not code:
        return fail("请输入激活码")
    try:
        st = lic.activate(code)
    except ValueError as e:
        return fail(str(e))
    return ok(**st)


@app.get("/api/health")
async def health():
    return ok(time=db.now(), version="1.0.0", scheduler=scheduler.state())


# ==================== 首页统计 ====================
@app.get("/api/dashboard")
async def api_dashboard():
    cfg = load_config()
    ui = cfg.get("ui") or {}
    d = stats.dashboard()
    d["ui"] = {"greeting": (ui.get("greeting") or "").strip()}
    return ok(**d)


@app.get("/api/stats/activity")
async def api_activity(limit: int = 30):
    return ok(rows=stats.activity(limit))


@app.post("/api/registry/sync")
async def api_registry_sync():
    return ok(**archive.sync_registry())


# ==================== 档案库 ====================
@app.post("/api/vault/scan")
async def api_scan():
    stat = vault.scan_vault()
    reg = archive.sync_registry()
    n = workflow.rebuild_case_reminders()
    return ok(stat=stat, registry=reg, reminders=n)


@app.get("/api/vault/tree")
async def api_tree():
    """仅 Markdown 笔记树（双链视图用）；全类型文件树见 /api/archive/tree。"""
    return ok(tree=_md_tree())


def _md_tree():
    roots = []
    for top in sorted(VAULT_DIR.iterdir()):
        if top.is_dir():
            children = [{"name": f.stem, "path": vault.rel(f), "children": []}
                        for f in sorted(top.rglob("*.md"))]
            roots.append({"name": top.name, "path": None, "children": children})
        elif top.suffix == ".md":
            roots.append({"name": top.stem, "path": vault.rel(top), "children": []})
    return roots


@app.get("/api/note")
async def api_get_note(path: str):
    try:
        p = vault.abs_path(path)
        text = p.read_text(encoding="utf-8")
        fm, body = vault.parse_frontmatter(text)
        return ok(path=path, text=text, frontmatter=fm, body=body,
                  backlinks=vault.backlinks(path))
    except Exception as e:
        return fail(f"读取失败：{e}")


@app.post("/api/note/save")
async def api_save_note(req: Request):
    d = await req.json()
    try:
        path = vault.write_note(d["path"], d["text"])
        vault.scan_vault()
        workflow.rebuild_case_reminders()
        db.audit("保存笔记", path)
        return ok(path=path)
    except Exception as e:
        return fail(f"保存失败：{e}")


@app.post("/api/note/create")
async def api_create_note(req: Request):
    d = await req.json()
    folder = (d.get("folder") or "笔记").strip()
    title = (d.get("title") or "未命名").strip()
    fm = d.get("frontmatter") or {}
    body = d.get("body", "")
    rel_path = f"{folder}/{title}.md"
    if (VAULT_DIR / rel_path).exists():
        return fail("同名笔记已存在")
    vault.write_note(rel_path, vault.dump_frontmatter(fm, f"# {title}\n\n{body}"))
    vault.scan_vault()
    archive.sync_registry()
    return ok(path=rel_path)


@app.get("/api/search")
async def api_search(q: str):
    return ok(hits=vault.search(q))


@app.get("/api/graph")
async def api_graph():
    return ok(**vault.graph_data())


@app.get("/api/backlinks")
async def api_backlinks(path: str):
    return ok(backlinks=vault.backlinks(path))


# ---------------- 档案总表（多维表格） ----------------
@app.get("/api/archive/tree")
async def api_archive_tree():
    return ok(tree=archive.tree())


@app.get("/api/archive/table")
async def api_archive_table(keyword: str = "", category: str = "", client: str = "",
                            starred: int = 0, sort: str = "updated", desc: int = 1,
                            limit: int = 1000):
    rows = archive.table_rows(keyword=keyword, category=category, client=client,
                              starred=bool(starred), sort=sort, desc=bool(desc), limit=limit)
    facets = {
        "categories": [r["category"] for r in
                       db.query("SELECT DISTINCT category FROM doc_registry WHERE category!=''")],
        "clients": [r["client"] for r in
                    db.query("SELECT DISTINCT client FROM doc_registry WHERE client!=''")],
        "cases": [r["case_ref"] for r in
                  db.query("SELECT DISTINCT case_ref FROM doc_registry WHERE case_ref!=''")],
    }
    return ok(rows=rows, count=len(rows), facets=facets)


@app.post("/api/archive/fields")
async def api_archive_fields(req: Request):
    d = await req.json()
    try:
        return ok(row=archive.update_fields(d["path"], d.get("patch", {})))
    except Exception as e:
        return fail(str(e))


@app.post("/api/archive/open")
async def api_archive_open(req: Request):
    d = await req.json()
    try:
        return ok(**archive.open_local(d["path"]))
    except Exception as e:
        return fail(str(e))


@app.post("/api/archive/reveal")
async def api_archive_reveal(req: Request):
    d = await req.json()
    try:
        return ok(**archive.reveal(d["path"]))
    except Exception as e:
        return fail(str(e))


@app.post("/api/archive/open-folder")
async def api_archive_open_folder(req: Request):
    d = await req.json()
    try:
        return ok(**archive.open_folder(d.get("path", "")))
    except Exception as e:
        return fail(str(e))


@app.post("/api/archive/rename")
async def api_archive_rename(req: Request):
    d = await req.json()
    try:
        return ok(**archive.rename(d["path"], d["name"]))
    except Exception as e:
        return fail(str(e))


@app.post("/api/archive/delete")
async def api_archive_delete(req: Request):
    d = await req.json()
    try:
        return ok(**archive.delete(d["path"]))
    except Exception as e:
        return fail(str(e))


@app.post("/api/archive/new-folder")
async def api_archive_new_folder(req: Request):
    d = await req.json()
    try:
        return ok(**archive.new_folder(d.get("parent", ""), d.get("name", "")))
    except Exception as e:
        return fail(str(e))


@app.post("/api/archive/upload")
async def api_archive_upload(files: list[UploadFile] = File(...), folder: str = Form("")):
    saved = []
    for up in files:
        data = await up.read()
        try:
            saved.append(archive.save_upload(folder, up.filename or "未命名", data))
        except Exception as e:
            saved.append({"ok": False, "error": str(e), "name": up.filename})
    return ok(saved=saved)


@app.post("/api/archive/import-folder")
async def api_archive_import_folder(req: Request):
    """一键导入：用户指定本地文件夹，递归扫描并智能匹配客户/案件后纳入档案库管理。"""
    d = await req.json()
    try:
        return ok(**archive.import_folder(d.get("dir", ""), bool(d.get("move", False))))
    except Exception as e:
        return fail(str(e))


@app.get("/api/archive/detail")
async def api_archive_detail(path: str):
    try:
        return ok(**archive.detail(path))
    except Exception as e:
        return fail(str(e))


# ---------------- 接案笔录（v0.9.8） ----------------

@app.post("/api/intake/transcribe")
async def api_intake_transcribe(file: UploadFile = File(...),
                                started_at: str = Form(""), client: str = Form(""),
                                lawyer: str = Form(""), recorder: str = Form(""),
                                location: str = Form("")):
    """上传录音 → 本地转写、角色区分、要素提取，建立接案笔录草稿。"""
    raw = await file.read()
    if not raw:
        return fail("录音为空")
    try:
        r = intake.create_from_audio(raw, file.filename or "audio.webm",
                                     started_at=started_at, client=client,
                                     lawyer=lawyer, recorder=recorder, location=location)
        return ok(**r)
    except Exception as e:
        return fail(f"转写失败：{e}")


@app.get("/api/intake/list")
async def api_intake_list():
    return ok(rows=intake.list_records())


@app.get("/api/intake/get")
async def api_intake_get(id: int):
    return ok(**intake.get_record(id))


@app.post("/api/intake/generate")
async def api_intake_generate(req: Request):
    d = await req.json()
    try:
        return ok(**intake.generate(int(d["id"]), d.get("meta") or {}, d.get("turns") or []))
    except Exception as e:
        return fail(f"生成笔录失败：{e}")


@app.post("/api/intake/retranscribe")
async def api_intake_retranscribe(req: Request):
    d = await req.json()
    try:
        return ok(**intake.retranscribe(int(d["id"])))
    except Exception as e:
        return fail(f"重新转写失败：{e}")


@app.post("/api/intake/open")
async def api_intake_open(req: Request):
    d = await req.json()
    return ok(**intake.open_target(int(d["id"]), d.get("target", "docx")))


@app.post("/api/intake/delete")
async def api_intake_delete(req: Request):
    d = await req.json()
    return ok(**intake.delete_record(int(d["id"]), bool(d.get("delete_files", True))))


# ---------------- 本地 OCR（多模态工具箱已取消，仅保留档案库内 OCR 识别能力） ----------------

_OCR_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"}


@app.get("/api/media/caps")
async def api_media_caps():
    return ok(caps=media.capabilities())


@app.post("/api/media/ocr")
async def api_media_ocr(file: UploadFile = File(...)):
    data = await file.read()
    r = media.ocr_image(data)
    if not r.get("ok"):
        return fail(r.get("error", "OCR识别失败"))
    return ok(engine=r.get("engine", ""), text=r.get("text", ""))


@app.post("/api/media/ocr-path")
async def api_media_ocr_path(req: Request):
    """对档案库内已有图片做 OCR，可选把结果保存为同名 Markdown 笔记。"""
    d = await req.json()
    p = archive._safe_path(d["path"])
    if not p.exists() or not p.is_file():
        return fail("文件不存在", 404)
    if p.suffix.lower() not in _OCR_EXTS:
        return fail("仅支持图片文件（png/jpg/jpeg/bmp/webp/tif）")
    r = media.ocr_image(p.read_bytes())
    if not r.get("ok"):
        return fail(r.get("error", "OCR识别失败"))
    text = (r.get("text") or "").strip()
    note_path = ""
    if d.get("save_note") and text:
        note = p.with_suffix(".md")
        note.write_text(
            f"---\ntype: OCR识别\nsource: \"[[{p.name}]]\"\ncreated: {db.now()}\n---\n\n"
            f"# {p.stem}（OCR 识别结果）\n\n{text}\n", encoding="utf-8")
        note_path = note.name
        vault.scan_vault()
        archive.sync_registry()
    db.audit("OCR识别", f"{p.name} → {len(text)} 字")
    return ok(engine=r.get("engine", ""), text=text, note=note_path)


@app.get("/api/file/download")
async def api_download(path: str):
    try:
        p = archive._safe_path(path)
    except Exception:
        p = vault.abs_path(path)
    return FileResponse(p, filename=p.name)


@app.get("/api/file/raw")
async def api_raw(path: str):
    """供前端内嵌预览（图片/PDF）。"""
    try:
        p = archive._safe_path(path)
        if not p.exists():
            return fail("文件不存在", 404)
        return FileResponse(p)
    except Exception as e:
        return fail(str(e))


# ==================== 案件类型 ====================
@app.get("/api/case-types")
async def api_case_types(all: int = 1):
    return ok(types=casetypes.list_types(bool(all)), grouped=casetypes.grouped())


@app.post("/api/case-types")
async def api_case_type_add(req: Request):
    d = await req.json()
    try:
        return ok(type=casetypes.add_type(d.get("name", ""), d.get("category", "自定义"),
                                          d.get("flow", "nonlit_generic")))
    except Exception as e:
        return fail(str(e))


@app.patch("/api/case-types/{tid}")
async def api_case_type_update(tid: int, req: Request):
    try:
        return ok(type=casetypes.update_type(tid, await req.json()))
    except Exception as e:
        return fail(str(e))


@app.delete("/api/case-types/{tid}")
async def api_case_type_delete(tid: int):
    try:
        return ok(**casetypes.delete_type(tid))
    except Exception as e:
        return fail(str(e))


@app.post("/api/case-types/reorder")
async def api_case_type_reorder(req: Request):
    d = await req.json()
    return ok(**casetypes.reorder(d.get("ids", [])))


@app.get("/api/case-types/flow")
async def api_case_flow(flow: str = "nonlit_generic"):
    return ok(flow=flow, stages=casetypes.flow_preview(flow),
              options=casetypes.stage_options(flow),
              nonlit_keys=sorted(casetypes.NONLIT_FLOWS.keys()))


@app.get("/api/case/check-cause")
async def api_case_check_cause(case_type: str = "", cause: str = ""):
    g = workflow.cause_guard(case_type, cause)
    ai = {"available": False}
    # 有本地模型时，用 AI 二次把关（短超时，不阻塞建案）
    try:
        if ai_hub.status().get("reachable"):
            sys = ("你是律师工作台案件分类助手。判断「案件类型：{t}」与「案由：{c}」是否匹配，"
                   "只用一句话回答：匹配 / 不匹配及理由（不超过30字）。"
                   .format(t=case_type or "未选", c=cause))
            r = ai_hub.one_shot(f"案件类型：{case_type or '未选'}；案由：{cause}", sys, timeout=6.0)
            ai = {"available": True, "ok": r.get("ok", False), "text": r.get("text", "")}
    except Exception:
        pass
    return ok(guard=g, ai=ai)


# ==================== 客户 ====================
@app.get("/api/clients")
async def api_clients():
    rows = db.query("SELECT rel_path,title,frontmatter FROM files WHERE ftype='client' ORDER BY title")
    out = []
    for r in rows:
        try:
            fm = json.loads(r["frontmatter"] or "{}")
        except Exception:
            fm = {}
        cnt = db.query_one("SELECT COUNT(*) c FROM cases WHERE client=?", (r["title"],))["c"]
        amt = db.query_one("SELECT COALESCE(SUM(amount),0) s FROM fee_records WHERE client=?",
                           (r["title"],))["s"] or 0
        out.append({"rel_path": r["rel_path"], "title": r["title"], "cases": cnt,
                    "amount": round(amt, 2), **{k: v for k, v in fm.items()
                                                if k in ("联系方式", "身份证/统一信用代码",
                                                         "对方当事人", "地址", "备注")}})
    return ok(clients=out)


def ensure_client_note(name: str, extra: dict | None = None) -> str:
    """建案时自动同步客户档案：客户笔记不存在则自动建档，已存在则原样保留（不覆盖用户已录信息）。"""
    name = (name or "").strip()
    rel_path = f"客户/{name}.md"
    cp = VAULT_DIR / rel_path
    if not cp.exists():
        e = extra or {}
        fm = {"type": "client", "标题": name, "联系方式": e.get("contact", ""),
              "身份证/统一信用代码": e.get("idno", ""), "对方当事人": e.get("opponent", ""),
              "地址": e.get("address", ""), "备注": "新建案件时自动建档",
              "最近联系": db.today()}
        body = (f"# {name}\n\n## 基本信息\n- 联系方式：{e.get('contact','')}\n"
                f"- 证件号码：{e.get('idno','')}\n- 地址：{e.get('address','')}\n"
                f"- 对方当事人：{e.get('opponent','')}\n\n"
                f"## 关联案件\n\n## 沟通记录\n")
        vault.write_note(rel_path, vault.dump_frontmatter(fm, body))
    return rel_path


@app.post("/api/clients")
async def api_create_client(req: Request):
    d = await req.json()
    name = (d.get("name") or "").strip()
    if not name:
        return fail("客户名称必填")
    rel_path = f"客户/{name}.md"
    if (VAULT_DIR / rel_path).exists():
        return fail("客户已存在")
    fm = {"type": "client", "标题": name, "联系方式": d.get("contact", ""),
          "身份证/统一信用代码": d.get("idno", ""), "对方当事人": d.get("opponent", ""),
          "地址": d.get("address", ""), "备注": d.get("note", ""),
          "最近联系": db.today()}
    body = (f"# {name}\n\n## 基本信息\n- 联系方式：{d.get('contact','')}\n"
            f"- 证件号码：{d.get('idno','')}\n- 地址：{d.get('address','')}\n\n"
            f"## 关联案件\n\n## 沟通记录\n")
    vault.write_note(rel_path, vault.dump_frontmatter(fm, body))
    vault.scan_vault()
    archive.sync_registry()
    return ok(path=rel_path)


@app.get("/api/client/detail")
async def api_client_detail(path: str):
    try:
        p = vault.abs_path(path)
        fm, body = vault.parse_frontmatter(p.read_text(encoding="utf-8"))
        cases = db.query("SELECT * FROM cases WHERE client=? ORDER BY updated DESC",
                         (fm.get("标题") or Path(path).stem,))
        fees = db.query("SELECT * FROM fee_records WHERE client=? ORDER BY fee_date DESC",
                        (fm.get("标题") or Path(path).stem,))
        return ok(frontmatter=fm, body=body, cases=[_flow_of_case(c) for c in cases], fees=fees)
    except Exception as e:
        return fail(str(e))


# ==================== 案件 ====================
@app.get("/api/cases")
async def api_cases(keyword: str = "", category: str = "", stage: str = ""):
    vault.scan_vault()
    rows = _case_rows_with_flow()
    if category:
        rows = [r for r in rows if (r.get("case_category") or "") == category]
    if stage:
        rows = [r for r in rows if (r.get("stage") or "") == stage]
    if keyword:
        kw = keyword.lower()
        rows = [r for r in rows if kw in f"{r.get('client','')}{r.get('cause','')}"
                f"{r.get('case_no','')}{r.get('court','')}{r.get('case_type','')}".lower()]
    for r in rows:
        tl = workflow.timeline_for(r)
        overdue = [t for t in tl if "逾期" in (t.get("status") or "")]
        near = [t for t in tl if "临近" in (t.get("status") or "")]
        r["alert"] = len(overdue)
        r["warning"] = len(near)
        r["next_due"] = next((t["due"] for t in tl if t.get("due") and
                              not (t.get("status") or "").startswith(("已完成", "未触发"))), "")
        r["node_count"] = len(tl)
        done = sum(1 for t in tl if (t.get("status") or "").startswith("已完成"))
        r["flow_progress"] = round(done / len(tl) * 100) if tl else 0
    return ok(cases=rows, today=db.today())


def _case_map(fm: dict) -> dict:
    return {
        "client": fm.get("客户", ""), "cause": fm.get("案由", ""),
        "procedure": fm.get("程序", "普通程序"), "stage": fm.get("阶段", "委托"),
        "contact_date": fm.get("委托日期", ""), "filing_date": fm.get("立案日期", ""),
        "hearing_date": fm.get("开庭日期", ""), "judgment_date": fm.get("判决日期", ""),
        "judgment_eff_date": fm.get("生效日期", ""), "judgment_type": fm.get("裁判类型", "判决"),
        "case_type": fm.get("案件类型", ""), "case_category": fm.get("业务类别", ""),
    }


@app.post("/api/cases")
async def api_create_case(req: Request):
    d = await req.json()
    client = (d.get("client") or "").strip()
    cause = (d.get("cause") or "").strip()
    if not client or not cause:
        return fail("客户与案由必填")
    name = f"{client}-{cause}"
    rel_path = f"案件/{name}.md"
    if (VAULT_DIR / rel_path).exists():
        return fail("该客户+案由的案件已存在")

    case_type = (d.get("case_type") or "").strip()
    t = db.query_one("SELECT * FROM case_types WHERE name=?", (case_type,)) if case_type else None
    category = (t["category"] if t else (d.get("case_category") or "诉讼仲裁"))
    flow = (t["flow"] if t else "civil_flow")
    stage = (d.get("stage") or "").strip()
    if not stage:
        stage = casetypes.stage_options(flow)[0] if flow.startswith("nonlit") else "委托"

    fm = {"type": "case", "标题": name, "客户": client,
          "客户链接": f"[[客户/{client}]]", "案由": cause,
          "案件类型": case_type, "业务类别": category,
          "管辖法院": d.get("court", ""), "程序": d.get("procedure", "普通程序"),
          "阶段": stage, "案号": d.get("case_no", ""),
          "对方当事人": d.get("opponent", ""),
          "委托日期": d.get("contact_date", ""), "立案日期": d.get("filing_date", ""),
          "开庭日期": d.get("hearing_date", ""), "判决日期": d.get("judgment_date", ""),
          "裁判类型": "判决", "生效日期": d.get("judgment_eff_date", ""),
          "律师费": d.get("fee_amount", 0), "收费方式": d.get("fee_method", ""),
          "标的额": d.get("subject_amount", 0), "风险等级": d.get("risk_level", "中"),
          "优先级": d.get("priority", "普通"), "标签": d.get("tags", "")}
    body = (f"# {name}\n\n## 案件概要\n- 客户：[[客户/{client}]]\n- 案件类型：{case_type}（{category}）\n"
            f"- 案由：{cause}\n- 管辖机构：{d.get('court','')}\n"
            f"- 律师费：{d.get('fee_amount',0)} 元（{d.get('fee_method','')}）\n\n"
            f"## 事实经过\n\n## 诉讼请求/服务目标\n\n## 证据目录\n\n## 办案日志\n")
    vault.write_note(rel_path, vault.dump_frontmatter(fm, body))

    # 客户档案自动同步：不存在则自动建档（需求：添加案件时客户信息自动同步到客户管理）
    ensure_client_note(client, {"opponent": d.get("opponent", "")})
    # 客户笔记回链
    cp = VAULT_DIR / f"客户/{client}.md"
    if cp.exists():
        txt = cp.read_text(encoding="utf-8")
        if f"[[案件/{name}]]" not in txt:
            cp.write_text(txt.rstrip() + f"\n- [[案件/{name}]]\n", encoding="utf-8")

    db.execute("UPDATE cases SET case_type=?, case_category=?, contact_date=?, opponent=?, "
               "fee_amount=?, fee_method=?, subject_amount=?, risk_level=?, priority=?, tags=? "
               "WHERE rel_path=?",
               (case_type, category, d.get("contact_date", ""), d.get("opponent", ""),
                float(d.get("fee_amount") or 0), d.get("fee_method", ""),
                float(d.get("subject_amount") or 0), d.get("risk_level", "中"),
                d.get("priority", "普通"), d.get("tags", ""), rel_path))

    # 律师费前置录入：如填写金额则自动登记一条创收（律师费）记录
    if float(d.get("fee_amount") or 0) > 0:
        revenue.add_record({"record_type": "律师费", "case_path": rel_path, "client": client,
                            "title": f"{cause}·律师费", "amount": float(d["fee_amount"]),
                            "fee_date": d.get("contact_date") or db.today(),
                            "method": d.get("fee_method") or "银行转账",
                            "note": "新建案件时录入" if d.get("fee_received") else
                                    "合同约定金额（待回款）"})
        if not d.get("fee_received"):
            db.execute("UPDATE cases SET fee_paid=0 WHERE rel_path=?", (rel_path,))

    vault.scan_vault()
    workflow.rebuild_case_reminders()
    archive.sync_registry()
    return ok(path=rel_path, flow=flow, stage=stage)


@app.post("/api/cases/import-scan")
async def api_cases_import_scan(req: Request):
    d = await req.json()
    try:
        return ok(**case_import.scan(d.get("folder", "")))
    except Exception as e:
        return fail(str(e))


@app.post("/api/cases/import-commit")
async def api_cases_import_commit(req: Request):
    d = await req.json()
    try:
        return ok(**case_import.commit(d.get("folder", ""), d.get("groups", []),
                                       bool(d.get("move", False))))
    except Exception as e:
        return fail(str(e))


@app.get("/api/case/detail")
async def api_case_detail(path: str):
    try:
        p = vault.abs_path(path)
        fm, _ = vault.parse_frontmatter(p.read_text(encoding="utf-8"))
        cm = _case_map(fm)
        row = db.query_one("SELECT * FROM cases WHERE rel_path=?", (path,)) or {}
        cm = {**cm, **{k: v for k, v in row.items() if v not in (None, "")}}
        _flow_of_case(cm)
        timeline = workflow.timeline_for(cm)
        gen = set(docgen.generated_types(path))
        checklist = workflow.match_checklist(cm, gen)
        docs = docgen.list_case_docs(path)
        fee = revenue.case_fee(path)
        stage_opts = (casetypes.stage_options(cm.get("flow", ""))
                      if (cm.get("flow") or "").startswith("nonlit") else workflow.STAGE_ORDER)
        return ok(frontmatter=fm, timeline=timeline, checklist=checklist, docs=docs,
                  fee=fee, stage_options=stage_opts, flow=cm.get("flow", ""),
                  row=row)
    except Exception as e:
        return fail(f"案件读取失败：{e}")


@app.post("/api/case/update-meta")
async def api_update_meta(req: Request):
    d = await req.json()
    p = vault.abs_path(d["path"])
    text = p.read_text(encoding="utf-8")
    fm, body = vault.parse_frontmatter(text)
    fm.update(d.get("patch", {}))
    vault.write_note(d["path"], vault.dump_frontmatter(fm, body))
    vault.scan_vault()
    # 同步结构化列
    m = {"案件类型": "case_type", "业务类别": "case_category", "对方当事人": "opponent",
         "律师费": "fee_amount", "收费方式": "fee_method", "标的额": "subject_amount",
         "风险等级": "risk_level", "优先级": "priority", "标签": "tags",
         "委托日期": "contact_date"}
    sets, args = [], []
    for cn, col in m.items():
        if cn in fm:
            val = fm[cn]
            if col in ("fee_amount", "subject_amount"):
                try:
                    val = float(val or 0)
                except ValueError:
                    val = 0.0
            sets.append(f"{col}=?"); args.append(val)
    if sets:
        args.append(d["path"])
        db.execute(f"UPDATE cases SET {','.join(sets)}, updated=? WHERE rel_path=?",
                   tuple(args[:-1] + [db.now(), d["path"]]))
    workflow.rebuild_case_reminders()
    return ok()


@app.post("/api/case/gen-doc")
async def api_gen_doc(req: Request):
    d = await req.json()
    fm, _ = vault.parse_frontmatter(vault.abs_path(d["case_path"]).read_text(encoding="utf-8"))
    res = docgen.create_doc(d["case_path"], fm.get("客户", ""), fm.get("案由", ""),
                            d["doc_type"], d.get("basis", ""))
    archive.sync_registry()
    return ok(**res)


@app.post("/api/case/gen-all")
async def api_gen_all(req: Request):
    d = await req.json()
    fm, _ = vault.parse_frontmatter(vault.abs_path(d["case_path"]).read_text(encoding="utf-8"))
    cm = _case_map(fm)
    row = db.query_one("SELECT * FROM cases WHERE rel_path=?", (d["case_path"],)) or {}
    cm = {**cm, **{k: v for k, v in row.items() if v not in (None, "")}}
    _flow_of_case(cm)
    checklist = workflow.match_checklist(cm, docgen.generated_types(d["case_path"]))
    made = []
    for item in checklist:
        if item["need_level"] == "必备" and not item["generated"]:
            made.append(docgen.create_doc(d["case_path"], fm.get("客户", ""),
                                          fm.get("案由", ""), item["doc_type"], item["basis"]))
    archive.sync_registry()
    return ok(made=made)


# ==================== 模板文书库（起诉状/答辩状/诉讼保全） ====================
@app.get("/api/doc-templates")
async def api_doc_templates(q: str = "", group: str = "", category: str = ""):
    try:
        return ok(**doctpl.list_templates(q=q, group=group, category=category))
    except Exception as e:
        return fail(f"模板库读取失败：{e}")


@app.get("/api/doc-templates/recommend")
async def api_doc_templates_recommend(path: str):
    try:
        return ok(matched=doctpl.recommend(path))
    except Exception as e:
        return fail(f"模板推荐失败：{e}")


@app.get("/api/doc-templates/preview")
async def api_doc_templates_preview(id: int):
    try:
        return ok(text=doctpl.preview(id))
    except Exception as e:
        return fail(f"模板预览失败：{e}")


@app.post("/api/doc-templates/gen")
async def api_doc_templates_gen(req: Request):
    d = await req.json()
    try:
        res = doctpl.generate(int(d["id"]), d["case_path"])
        archive.sync_registry()
        return ok(**res)
    except Exception as e:
        return fail(f"模板文书生成失败：{e}")


@app.get("/api/doc-templates/form-schema")
async def api_doc_templates_schema(id: int):
    try:
        return ok(**doctpl.form_schema(id))
    except Exception as e:
        return fail(f"表单 schema 读取失败：{e}")


@app.post("/api/doc-templates/gen-filled")
async def api_doc_templates_gen_filled(req: Request):
    d = await req.json()
    try:
        res = doctpl.generate_filled(int(d["id"]), d.get("values", {}), d["case_path"])
        archive.sync_registry()
        return ok(**res)
    except Exception as e:
        return fail(f"要素式文书生成失败：{e}")


@app.get("/api/case/fees")
async def api_case_fees(path: str):
    return ok(**revenue.case_fee(path))


# ==================== 文书同步比对 ====================
@app.get("/api/sync/pending")
async def api_sync_pending():
    docgen.rescan_disk_state()
    docs = db.query("SELECT * FROM gen_docs WHERE sync_state!='一致' ORDER BY id DESC")
    notes = db.query("SELECT * FROM reminders WHERE kind='文档同步' AND done=0")
    return ok(docs=docs, notes=notes)


@app.post("/api/sync/accept")
async def api_sync_accept(req: Request):
    d = await req.json()
    return ok(**docgen.accept_sync(int(d["id"])))


# ==================== 创收管理 ====================
@app.get("/api/revenue/records")
async def api_revenue_list(rtype: str = "", year: str = "", client: str = "",
                           case_path: str = "", keyword: str = ""):
    return ok(rows=revenue.list_records(rtype, year, client, case_path, keyword))


@app.post("/api/revenue/records")
async def api_revenue_add(req: Request):
    try:
        return ok(row=revenue.add_record(await req.json()))
    except Exception as e:
        return fail(str(e))


@app.patch("/api/revenue/records/{rid}")
async def api_revenue_update(rid: int, req: Request):
    try:
        return ok(row=revenue.update_record(rid, await req.json()))
    except Exception as e:
        return fail(str(e))


@app.delete("/api/revenue/records/{rid}")
async def api_revenue_delete(rid: int):
    try:
        return ok(**revenue.delete_record(rid))
    except Exception as e:
        return fail(str(e))


@app.get("/api/revenue/summary")
async def api_revenue_summary(year: str = ""):
    return ok(summary=revenue.summary(year), monthly=revenue.monthly(year),
              by_client=revenue.by_dimension("client", year),
              by_case=revenue.by_dimension("case", year),
              years=revenue.years(), meta={"types": revenue.types(),
                                           "methods": revenue.methods()})


# ==================== 发票管理 ====================
@app.get("/api/invoices")
async def api_invoices(keyword: str = "", month: str = ""):
    return ok(rows=invoice.list_invoices(keyword, month), stats=invoice.stats())


@app.get("/api/invoices/settings")
async def api_invoice_settings_get():
    return ok(settings=invoice.status())


@app.post("/api/invoices/settings")
async def api_invoice_settings_save(req: Request):
    try:
        return ok(settings=invoice.save_settings(await req.json()))
    except Exception as e:
        return fail(str(e))


@app.post("/api/invoices/fetch")
async def api_invoice_fetch():
    return ok(**invoice.fetch_from_mailbox())


@app.post("/api/invoices/import")
async def api_invoice_import(files: list[UploadFile] = File(...)):
    saved = []
    for up in files:
        data = await up.read()
        saved.append(invoice.import_local(data, up.filename or "发票"))
    return ok(saved=saved)


@app.post("/api/invoices/open")
async def api_invoice_open(req: Request):
    d = await req.json()
    row = db.query_one("SELECT * FROM invoices WHERE id=?", (int(d["id"]),))
    if not row:
        return fail("发票不存在")
    return ok(**archive._open_with_system(Path(row["file_path"])))


@app.post("/api/invoices/reveal")
async def api_invoice_reveal(req: Request):
    """在文件管理器中定位发票原件（路径相对 data/invoices）。"""
    d = await req.json()
    row = db.query_one("SELECT * FROM invoices WHERE id=?", (int(d["id"]),))
    if not row:
        return fail("发票不存在")
    rel = (row.get("rel_path") or "").replace("invoices/", "").lstrip("/")
    if not rel:
        return fail("发票路径无效")
    try:
        return ok(**archive.reveal(rel))
    except Exception as e:
        return fail(str(e))


@app.post("/api/invoices/{iid}/notify")
async def api_invoice_notify(iid: int):
    try:
        return ok(**invoice.notify_manual(iid))
    except Exception as e:
        return fail(str(e))


@app.patch("/api/invoices/{iid}")
async def api_invoice_note(iid: int, req: Request):
    d = await req.json()
    return ok(row=invoice.update_note(iid, d.get("note", "")))


@app.delete("/api/invoices/{iid}")
async def api_invoice_delete(iid: int, remove_file: int = 0):
    try:
        return ok(**invoice.delete_invoice(iid, bool(remove_file)))
    except Exception as e:
        return fail(str(e))


@app.get("/api/invoice/file")
async def api_invoice_file(id: int, download: int = 0):
    row = db.query_one("SELECT * FROM invoices WHERE id=?", (id,))
    if not row or not Path(row["file_path"]).exists():
        return fail("发票文件不存在", 404)
    return FileResponse(row["file_path"], filename=row["file_name"],
                        media_type="application/octet-stream" if download else None)


# ==================== 飞书多维表格 ====================
@app.get("/api/bitable/status")
async def api_bitable_status():
    return ok(**bitable.status())


@app.get("/api/bitable/table")
async def api_bitable_table(dataset: str = "archive"):
    try:
        return ok(**bitable.table(dataset))
    except Exception as e:
        return fail(str(e))


@app.post("/api/bitable/sync")
async def api_bitable_sync(req: Request):
    d = await req.json()
    return ok(**bitable.sync(d.get("dataset", "archive"), bool(d.get("clear", True))))


@app.post("/api/bitable/export")
async def api_bitable_export(req: Request):
    d = await req.json()
    try:
        return ok(**bitable.export_csv(d.get("dataset", "archive")))
    except Exception as e:
        return fail(str(e))


@app.post("/api/bitable/settings")
async def api_bitable_settings(req: Request):
    return ok(**bitable.save_settings(await req.json()))


# ==================== AI 对话 ====================
@app.get("/api/ai/hub-status")
async def api_ai_hub_status():
    return ok(status=ai_hub.status(), providers=[{"key": k, "label": v["label"]}
                                                 for k, v in ai_hub.PROVIDERS.items()],
              quick=ai_hub.quick_actions())


@app.post("/api/ai/settings")
async def api_ai_settings(req: Request):
    try:
        return ok(**ai_hub.save_settings(await req.json()))
    except Exception as e:
        return fail(str(e))


@app.get("/api/ai/sessions")
async def api_ai_sessions():
    return ok(sessions=ai_hub.list_sessions())


@app.post("/api/ai/sessions")
async def api_ai_new_session(req: Request):
    d = await req.json()
    return ok(session=ai_hub.new_session(d.get("title", "新对话"), d.get("model", "")))


@app.get("/api/ai/sessions/{sid}")
async def api_ai_session(sid: int):
    try:
        return ok(session=ai_hub.get_session(sid), messages=ai_hub.messages(sid))
    except Exception as e:
        return fail(str(e))


@app.patch("/api/ai/sessions/{sid}")
async def api_ai_update_session(sid: int, req: Request):
    try:
        return ok(session=ai_hub.update_session(sid, await req.json()))
    except Exception as e:
        return fail(str(e))


@app.delete("/api/ai/sessions/{sid}")
async def api_ai_delete_session(sid: int):
    try:
        return ok(**ai_hub.delete_session(sid))
    except Exception as e:
        return fail(str(e))


@app.get("/api/ai/search")
async def api_ai_search(q: str = ""):
    """快速搜索本地档案库文档（含正文全文）。"""
    return ok(hits=ai_hub.search_vault(q))


@app.post("/api/ai/upload")
async def api_ai_upload(file: UploadFile = File(...), save_to_vault: str = Form("材料")):
    """上传文档并抽取文本（可同时保存原文件到档案库）。"""
    data = await file.read()
    if not data:
        return fail("文件为空")
    r = ai_hub.extract_text(file.filename or "未命名", data)
    if not r.get("ok"):
        return fail(r.get("error", "文档解析失败"))
    rel_path = ""
    if save_to_vault and save_to_vault != "none":
        try:
            rel_path = ai_hub.save_upload_to_vault(file.filename or "未命名", data, save_to_vault)
        except Exception as e:
            rel_path = ""
    db.audit("AI上传文档", f"{file.filename} -> {len(r.get('text',''))}字")
    return ok(name=r.get("name"), text=r.get("text"), engine=r.get("engine"),
              rel_path=rel_path)


@app.post("/api/ai/stream")
async def api_ai_stream(req: Request):
    """流式对话（POST，逐块返回 NDJSON 行）。"""
    d = await req.json()
    sid = int(d.get("session_id") or 0)
    question = (d.get("question") or "").strip()
    if not question:
        return fail("问题为空")
    if not sid:
        sid = ai_hub.new_session()["id"]

    def gen():
        for ev in ai_hub.stream_answer(sid, question, d.get("refs") or [],
                                       d.get("docs") or [], d.get("model")):
            yield json.dumps(ev, ensure_ascii=False) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson; charset=utf-8",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


# 保留：严格法律库问答（兼容旧调用）
@app.post("/api/ai/ask")
async def api_ai_ask(req: Request):
    d = await req.json()
    q = (d.get("question") or "").strip()
    if not q:
        return fail("问题为空")
    return ok(**llm.grounded_answer(q))


@app.get("/api/ai/status")
async def api_ai_status():
    st = llm.status()
    st["runtime"] = llm_runtime.status()
    return ok(**st)


@app.post("/api/ai/runtime/start")
async def api_ai_runtime_start():
    return ok(**llm_runtime.ensure_running())


@app.get("/api/ai/version-check")
async def api_ai_ver():
    return ok(**llm.version_check())


# ==================== 法律库 ====================
@app.get("/api/lawlib/status")
async def api_law_status():
    return ok(**lawlib.status())


@app.post("/api/lawlib/reindex")
async def api_law_reindex():
    return ok(**lawlib.build_index(force=True))


@app.get("/api/lawlib/list")
async def api_law_list():
    files = [{"name": f.stem, "size": f.stat().st_size,
              "mtime": datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M")}
             for f in sorted(LAWLIB_DIR.glob("*.md"))]
    return ok(files=files)


@app.post("/api/lawlib/import")
async def api_law_import(req: Request):
    d = await req.json()
    name = (d.get("name") or "").strip()
    text = d.get("text", "")
    if not name or not text:
        return fail("名称与正文必填")
    (LAWLIB_DIR / f"{_safe_law_name(name)}.md").write_text(text, encoding="utf-8")
    lawlib.build_index(force=True)
    return ok()


def _safe_law_name(name: str) -> str:
    return "".join(c for c in name if c not in '\\/:*?"<>|').strip() or "未命名法律"


@app.post("/api/lawlib/upload-files")
async def api_law_upload(files: list[UploadFile] = File(...)):
    saved = []
    for up in files:
        raw = await up.read()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("gb18030", errors="ignore")
        name = _safe_law_name((up.filename or "未命名").rsplit(".", 1)[0])
        (LAWLIB_DIR / f"{name}.md").write_text(text, encoding="utf-8")
        saved.append(name)
    if not saved:
        return fail("未收到有效文件")
    st = lawlib.build_index(force=True)
    db.audit("法律库批量导入", "、".join(saved))
    return ok(saved=saved, chunks=st["chunks"])


@app.post("/api/lawlib/import-folder")
async def api_law_import_folder(req: Request):
    d = await req.json()
    folder = Path(d.get("dir", ""))
    if not folder.exists() or not folder.is_dir():
        return fail("文件夹不存在或不是目录")
    saved = []
    for f in sorted(list(folder.glob("*.md")) + list(folder.glob("*.txt"))):
        try:
            text = f.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = f.read_text(encoding="gb18030", errors="ignore")
        (LAWLIB_DIR / f"{_safe_law_name(f.stem)}.md").write_text(text, encoding="utf-8")
        saved.append(f.stem)
    if not saved:
        return fail("该文件夹下没有 .md/.txt 文件")
    st = lawlib.build_index(force=True)
    db.audit("法律库文件夹导入", str(folder))
    return ok(saved=saved, chunks=st["chunks"])


# ==================== 提醒 / 日程 / 计时 / 通讯录 ====================
@app.get("/api/reminders")
async def api_reminders():
    workflow.rebuild_case_reminders()
    rows = db.query("SELECT * FROM reminders WHERE done=0 ORDER BY due ASC, level DESC")
    return ok(reminders=rows, lawlib=lawlib.status(),
              model_hints=llm.version_check()["hints"])


@app.post("/api/reminder/done")
async def api_reminder_done(req: Request):
    d = await req.json()
    db.execute("UPDATE reminders SET done=1 WHERE id=?", (int(d["id"]),))
    return ok()


@app.get("/api/tasks")
async def api_tasks(done: int = 0):
    return ok(rows=db.query("SELECT * FROM tasks WHERE done=? ORDER BY due ASC, level DESC",
                            (int(done),)))


@app.post("/api/tasks")
async def api_task_add(req: Request):
    d = await req.json()
    tid = db.insert("tasks", {"title": (d.get("title") or "").strip() or "未命名待办",
                              "detail": d.get("detail", ""), "due": d.get("due", db.today()),
                              "level": d.get("level", "普通"), "kind": d.get("kind", "待办"),
                              "case_path": d.get("case_path", ""), "done": 0,
                              "remind": d.get("remind", ""), "email": d.get("email", ""),
                              "reminded": 0, "created": db.now()})
    return ok(id=tid)


@app.patch("/api/tasks/{tid}")
async def api_task_update(tid: int, req: Request):
    d = await req.json()
    sets, args = [], []
    for f in ("title", "detail", "due", "level", "kind", "case_path", "remind", "email"):
        if f in d:
            sets.append(f"{f}=?"); args.append(d[f])
    if "done" in d:
        sets.append("done=?"); args.append(1 if d["done"] else 0)
    if sets:
        args.append(tid)
        db.execute(f"UPDATE tasks SET {','.join(sets)} WHERE id=?", tuple(args))
    return ok()


@app.delete("/api/tasks/{tid}")
async def api_task_delete(tid: int):
    db.execute("DELETE FROM tasks WHERE id=?", (tid,))
    return ok()


@app.get("/api/timer")
async def api_timer_list(case_path: str = ""):
    sql = "SELECT * FROM time_entries"
    args: list = []
    if case_path:
        sql += " WHERE case_path=?"; args.append(case_path)
    sql += " ORDER BY id DESC LIMIT 200"
    rows = db.query(sql, tuple(args))
    total = sum(r["seconds"] or 0 for r in rows)
    return ok(rows=rows, total_seconds=total, total_hours=round(total / 3600, 2))


@app.post("/api/timer")
async def api_timer_add(req: Request):
    d = await req.json()
    tid = db.insert("time_entries", {
        "case_path": d.get("case_path", ""), "title": d.get("title", "工作记录"),
        "started": d.get("started", ""), "ended": d.get("ended", ""),
        "seconds": int(d.get("seconds") or 0), "billable": 1 if d.get("billable", 1) else 0,
        "rate": float(d.get("rate") or 0), "note": d.get("note", ""), "created": db.now()})
    return ok(id=tid)


@app.delete("/api/timer/{tid}")
async def api_timer_delete(tid: int):
    db.execute("DELETE FROM time_entries WHERE id=?", (tid,))
    return ok()


# ==================== 设置与集成 ====================
@app.get("/api/settings")
async def api_settings_get():
    cfg = load_config()
    safe = json.loads(json.dumps(cfg))
    safe["feishu"].pop("app_secret", None)
    safe["feishu"]["app_secret_saved"] = bool(cfg["feishu"].get("app_secret_enc"))
    safe["wechat"].pop("appsecret", None)
    safe["wechat"]["appsecret_saved"] = bool(cfg["wechat"].get("appsecret_enc"))
    safe["invoice"].pop("password", None)
    safe["invoice"]["password_saved"] = bool(cfg.get("invoice", {}).get("password_enc"))
    safe["ai"].pop("api_key", None)
    safe["ai"]["api_key_saved"] = bool(cfg.get("ai", {}).get("api_key_enc"))
    safe["mail"].pop("password", None)
    safe["mail"]["password_saved"] = bool(cfg.get("mail", {}).get("password_enc"))
    safe["secret_store"] = {"available": SECRETS.available, "note": SECRETS.reason}
    safe["nav"] = db.kv_get("nav_order") or db.DEFAULT_NAV
    return ok(settings=safe, feishu=feishu.status(), wechat=wechat.status(),
              invoice=invoice.status(), bitable=bitable.status(), mail=mail.status(),
              ai=ai_hub.status(), scheduler=scheduler.state())


@app.post("/api/settings")
async def api_settings_save(req: Request):
    d = await req.json()
    cfg = load_config()
    if "llm" in d:
        cfg["llm"].update(d["llm"])
    if "security" in d:
        cfg["security"].update(d["security"])
    if "feishu" in d:
        f = d["feishu"]
        for k in ("enabled", "app_id", "folder_token"):
            if k in f:
                cfg["feishu"][k] = f[k]
        if f.get("app_secret"):
            if not SECRETS.available:
                return fail("加密组件不可用，为防泄露已拒绝保存密钥")
            cfg["feishu"]["app_secret_enc"] = SECRETS.encrypt(f["app_secret"])
    if "wechat" in d:
        w = d["wechat"]
        for k in ("enabled", "appid", "token", "open_kfid", "send_mode",
                  "template_id", "default_openid", "sandbox"):
            if k in w:
                cfg["wechat"][k] = w[k]
        if w.get("appsecret"):
            if not SECRETS.available:
                return fail("加密组件不可用，为防泄露已拒绝保存密钥")
            cfg["wechat"]["appsecret_enc"] = SECRETS.encrypt(w["appsecret"])
    if "ai" in d:
        ai = d["ai"]
        for k in ("provider", "base_url", "model", "temperature", "max_context_messages",
                  "system_prompt", "strict_law_only", "timeout"):
            if k in ai:
                cfg["ai"][k] = ai[k]
        if ai.get("api_key"):
            if not SECRETS.available:
                return fail("加密组件不可用，为防泄露已拒绝保存 API Key")
            cfg["ai"]["api_key_enc"] = SECRETS.encrypt(ai["api_key"])
    if "invoice" in d:
        inv = d["invoice"]
        for k in ("enabled", "imap_host", "imap_port", "imap_ssl", "username",
                  "folder", "days", "only_unseen", "keywords", "auto_notify",
                  "interval_minutes"):
            if k in inv:
                cfg["invoice"][k] = inv[k]
        if inv.get("password"):
            if not SECRETS.available:
                return fail("加密组件不可用，为防泄露已拒绝保存邮箱密码")
            cfg["invoice"]["password_enc"] = SECRETS.encrypt(inv["password"])
    if "bitable" in d:
        bt = d["bitable"]
        for k in ("app_token", "table_ids"):
            if k in bt:
                cfg["bitable"][k] = bt[k]
    if "mail" in d:
        ml = d["mail"]
        for k in ("enabled", "smtp_host", "smtp_port", "ssl", "username", "from_name", "to_addr"):
            if k in ml:
                cfg["mail"][k] = ml[k]
        if ml.get("password"):
            if not SECRETS.available:
                return fail("加密组件不可用，为防泄露已拒绝保存邮箱授权码")
            cfg["mail"]["password_enc"] = SECRETS.encrypt(ml["password"])
    if "ui" in d:
        ui = d["ui"]
        cfg.setdefault("ui", {})
        for k in ("greeting",):
            if k in ui:
                cfg["ui"][k] = str(ui[k] or "").strip()
    save_config(cfg)
    db.audit("修改设置", "设置已更新")
    return ok()


@app.get("/api/nav")
async def api_nav_get():
    saved = db.kv_get("nav_order") or db.DEFAULT_NAV
    # 新版本新增功能自动补入（保留用户排序）
    have = {n.get("key") for n in saved} if isinstance(saved, list) else set()
    if isinstance(saved, list):
        merged = list(saved)
        for n in db.DEFAULT_NAV:
            if n["key"] not in have:
                merged.append(dict(n))
        saved = merged
    return ok(items=saved)


@app.post("/api/nav")
async def api_nav_save(req: Request):
    d = await req.json()
    items = d.get("items") or []
    known = {n["key"]: n for n in db.DEFAULT_NAV}
    cleaned = []
    for it in items:
        k = it.get("key")
        if k in known:
            cleaned.append({"key": k, "name": it.get("name") or known[k]["name"],
                            "icon": known[k]["icon"],
                            "enabled": bool(it.get("enabled", True))})
    for n in db.DEFAULT_NAV:
        if n["key"] not in {c["key"] for c in cleaned}:
            cleaned.append(n)
    db.kv_set("nav_order", cleaned)
    return ok(items=cleaned)


@app.post("/api/nav/reset")
async def api_nav_reset():
    db.kv_set("nav_order", db.DEFAULT_NAV)
    return ok(items=db.DEFAULT_NAV)


@app.get("/api/feishu/status")
async def api_fs_status():
    return ok(**feishu.status())


@app.post("/api/feishu/sync")
async def api_fs_sync(req: Request):
    d = await req.json()
    res = feishu.sync_file(str(vault.abs_path(d["path"])))
    db.audit("飞书同步", f"{d['path']} -> {res.get('ok')}")
    return ok(**res)


@app.get("/api/wechat/status")
async def api_wx_status():
    return ok(**wechat.status())


@app.get("/api/outbox")
async def api_outbox():
    return ok(rows=db.query("SELECT * FROM outbox ORDER BY id DESC LIMIT 100"))


@app.post("/api/wechat/send")
async def api_wx_send(req: Request):
    d = await req.json()
    return ok(**wechat.send_one(int(d["id"])))


@app.post("/api/wechat/test-send")
async def api_wx_test(req: Request):
    d = await req.json()
    cfg = load_config()["wechat"]
    openid = (d.get("openid") or cfg.get("default_openid", "")).strip()
    content = (d.get("content") or "【测试】法岩律师工作台微信提醒通道已连通。").strip()
    res = wechat.send_text(openid, content, d.get("mode") or cfg.get("send_mode"))
    db.audit("微信测试发送", f"{cfg.get('send_mode')} -> {openid}: {res.get('ok')}")
    return ok(**res)


@app.get("/api/audit")
async def api_audit():
    lines = AUDIT_PATH.read_text(encoding="utf-8").splitlines()[-200:] if AUDIT_PATH.exists() else []
    return ok(lines=lines)


@app.get("/api/data/dir")
async def api_data_dir():
    return ok(data_dir=str(DATA_DIR), vault=str(VAULT_DIR), lawlib=str(LAWLIB_DIR))


# ==================== 演示数据 ====================
@app.post("/api/demo/seed")
async def api_demo():
    created = []
    if not (VAULT_DIR / "客户/张先生.md").exists():
        await api_create_client(_Json({"name": "张先生", "contact": "138****0000",
                                       "idno": "", "opponent": "某某科技有限公司",
                                       "address": "广东省惠州市惠城区"}))
        created.append("客户/张先生.md")
    if not (VAULT_DIR / "客户/某某贸易有限公司.md").exists():
        await api_create_client(_Json({"name": "某某贸易有限公司", "contact": "0752-****000",
                                       "idno": "91441300MA5XXXXX0A", "opponent": "",
                                       "address": "广东省惠州市"}))
        created.append("客户/某某贸易有限公司.md")
    if not (VAULT_DIR / "案件/张先生-劳动争议.md").exists():
        await api_create_case(_Json({
            "client": "张先生", "cause": "劳动争议", "court": "惠州市惠城区人民法院",
            "case_type": "劳动争议", "procedure": "简易程序", "stage": "委托",
            "contact_date": db.today(), "filing_date": db.today(),
            "fee_amount": 8000, "fee_method": "银行转账", "fee_received": False,
            "subject_amount": 120000, "risk_level": "中", "priority": "高"}))
        created.append("案件/张先生-劳动争议.md")
    if not (VAULT_DIR / "案件/某某贸易有限公司-常年法律顾问.md").exists():
        await api_create_case(_Json({
            "client": "某某贸易有限公司", "cause": "常年法律顾问",
            "court": "", "case_type": "常年法律顾问", "stage": "日常咨询与合同审查",
            "contact_date": db.today(), "fee_amount": 60000,
            "fee_method": "银行转账", "fee_received": True,
            "subject_amount": 0, "risk_level": "低", "priority": "普通"}))
        created.append("案件/某某贸易有限公司-常年法律顾问.md")
    vault.scan_vault()
    archive.sync_registry()
    workflow.rebuild_case_reminders()
    return ok(created=created)


# 静态前端（最后挂载，避免覆盖 /api）
if FRONTEND.exists():
    from fastapi.staticfiles import StaticFiles
    app.mount("/", StaticFiles(directory=str(FRONTEND), html=True), name="frontend")
