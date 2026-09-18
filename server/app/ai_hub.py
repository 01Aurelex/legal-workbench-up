# -*- coding: utf-8 -*-
"""开放 AI 对话能力（统一对话式助手）。

统一为一个对话式助手，不再划分模式，能力包括：
- 多轮对话 + 会话管理（新建/重命名/删除/历史消息持久化）
- 上传文档处理：上传 docx/pdf/md/txt/图片，抽取文本后按用户指令处理
- 调用本地文档：把档案库笔记/案件/材料挂载为上下文
- 快速搜索本地文档（含正文全文检索），结果可一键挂载
- 自动结合本地法律库检索结果作答，并逐条标注来源
- 流式输出（NDJSON），适配 Ollama 与任意 OpenAI 兼容端点；未配置 Key 时不外发内容
"""
from __future__ import annotations
import io
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Iterator

from .config import load_config
from .security import SECRETS
from . import db, lawlib, vault

PROVIDERS = {
    "bundled": {"label": "内置本地模型（随软件安装，开箱即用）",
                "path": "/v1/chat/completions", "models_path": "/v1/models", "openai_style": True},
    "ollama": {"label": "Ollama（本机自装）", "path": "/api/chat",
               "models_path": "/api/tags", "openai_style": False},
    "openai": {"label": "OpenAI 兼容端点（LM Studio / vLLM / 本地网关）",
               "path": "/v1/chat/completions", "models_path": "/v1/models",
               "openai_style": True},
}

DEFAULT_SYSTEM = (
    "你是「法岩律师工作台」内置的 AI 助手，服务于执业律师。要求：\n"
    "1. 使用简体中文，表述专业、克制，不夸大、不臆造；\n"
    "2. 涉及法律判断时优先援引现行有效的法律、司法解释并标注条文来源；\n"
    "3. 信息不足时主动说明缺少哪些材料，并给出获取路径；\n"
    "4. 输出面向专业人士：结论先行，后附依据与行动建议。\n"
    "5. 当用户上传或挂载了文档时，严格依据文档内容处理（归纳、审查、起草、改写、翻译等），"
    "引用处注明出处，不脱离文档编造。"
)

LAW_GUIDANCE = (
    "\n【法律依据提示】以下是本地法律库检索到的最相关条文摘录，"
    "回答法律问题时优先依据并标注「来源：法律名称 第X条」；"
    "若摘录不涉及该问题，应说明“本地法律库未检索到直接依据”，不得编造法条。"
)


def _cfg() -> dict:
    cfg = load_config()
    ai = cfg.get("ai") or {}
    llm = cfg.get("llm") or {}
    return {
        "provider": ai.get("provider") or llm.get("provider") or "bundled",
        "base_url": (ai.get("base_url") or llm.get("base_url") or "http://127.0.0.1:8766/v1").rstrip("/"),
        "model": ai.get("model") or llm.get("model") or "qwen2.5-3b-instruct-q4_k_m",
        "temperature": float(ai.get("temperature", 0.3)),
        "max_context_messages": int(ai.get("max_context_messages", 12)),
        "system_prompt": ai.get("system_prompt") or DEFAULT_SYSTEM,
        "strict_law_only": bool(ai.get("strict_law_only", True)),
        "timeout": float(ai.get("timeout", 240)),
    }


def api_key() -> str:
    ai = load_config().get("ai") or {}
    return SECRETS.decrypt(ai.get("api_key_enc", "")) or ai.get("api_key", "")


def status() -> dict:
    cfg = _cfg()
    info = {"reachable": False, "provider": cfg["provider"], "base_url": cfg["base_url"],
            "model": cfg["model"], "models": [], "error": ""}
    try:
        spec = PROVIDERS.get(cfg["provider"], PROVIDERS["ollama"])
        url = cfg["base_url"] + spec["models_path"]
        req = urllib.request.Request(url, method="GET")
        key = api_key()
        if key:
            req.add_header("Authorization", f"Bearer {key}")
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read().decode("utf-8"))
        info["reachable"] = True
        if spec["openai_style"]:
            info["models"] = [m.get("id") for m in data.get("data", [])]
        else:
            info["models"] = [m.get("name") for m in data.get("models", [])]
    except Exception as e:
        info["error"] = f"未连接到模型服务（{type(e).__name__}）：{e}"
    return info


# ---------------- 会话 ----------------
def list_sessions() -> list[dict]:
    rows = db.query("SELECT s.*, (SELECT COUNT(*) FROM ai_messages m WHERE m.session_id=s.id) c "
                    "FROM ai_sessions s ORDER BY updated DESC")
    return rows


def new_session(title: str = "新对话", model: str = "") -> dict:
    cfg = _cfg()
    sid = db.insert("ai_sessions", {"title": title or "新对话", "model": model or cfg["model"],
                                    "mode": "assistant", "system_prompt": cfg["system_prompt"],
                                    "created": db.now(), "updated": db.now()})
    return db.query_one("SELECT * FROM ai_sessions WHERE id=?", (sid,))


def get_session(sid: int) -> dict:
    row = db.query_one("SELECT * FROM ai_sessions WHERE id=?", (sid,))
    if not row:
        raise ValueError("会话不存在")
    return row


def update_session(sid: int, patch: dict) -> dict:
    row = get_session(sid)
    if "title" in patch:
        db.execute("UPDATE ai_sessions SET title=? WHERE id=?", (str(patch["title"])[:100], sid))
    if "model" in patch:
        db.execute("UPDATE ai_sessions SET model=? WHERE id=?", (patch["model"], sid))
    if "system_prompt" in patch:
        db.execute("UPDATE ai_sessions SET system_prompt=? WHERE id=?", (patch["system_prompt"], sid))
    return get_session(sid)


def delete_session(sid: int) -> dict:
    db.execute("DELETE FROM ai_messages WHERE session_id=?", (sid,))
    db.execute("DELETE FROM ai_sessions WHERE id=?", (sid,))
    return {"ok": True}


def messages(sid: int, limit: int = 200) -> list[dict]:
    return db.query("SELECT * FROM ai_messages WHERE session_id=? ORDER BY id ASC LIMIT ?",
                    (sid, limit))


# ---------------- 本地文档能力 ----------------
def search_vault(keyword: str, top_k: int = 20) -> list[dict]:
    """快速搜索本地档案库文档（含正文全文检索）。"""
    return vault.search(keyword)[:top_k]


def _context_from_refs(refs: list[str], max_chars: int = 6000) -> tuple[str, list[dict]]:
    """把档案库笔记路径列表拼接为上下文文本。"""
    parts, metas = [], []
    total = 0
    for ref in refs or []:
        try:
            p = vault.abs_path(ref)
            text = p.read_text(encoding="utf-8")
        except Exception:
            continue
        fm, body = vault.parse_frontmatter(text)
        chunk = body.strip()
        if len(chunk) > 2000:
            chunk = chunk[:2000] + "\n…（已截断）"
        if total + len(chunk) > max_chars:
            break
        parts.append(f"### {ref}\n{chunk}")
        metas.append({"path": ref, "title": fm.get("标题") or p.stem, "type": fm.get("type", "")})
        total += len(chunk)
    return "\n\n".join(parts), metas


def extract_text(filename: str, data: bytes) -> dict:
    """上传文档 → 抽取文本（docx/pdf/md/txt/图片 OCR）。"""
    name = filename or "未命名"
    ext = ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""
    if ext in (".md", ".txt", ".markdown"):
        for enc in ("utf-8", "gb18030"):
            try:
                return {"ok": True, "text": data.decode(enc), "engine": "text", "name": name}
            except UnicodeDecodeError:
                continue
        return {"ok": False, "error": "无法识别文本编码"}
    if ext == ".docx":
        try:
            import docx
            from docx import Document
            d = Document(io.BytesIO(data))
            paras = [p.text for p in d.paragraphs if p.text.strip()]
            # 表格内容
            for tb in d.tables:
                for row in tb.rows:
                    cells = [c.text.strip() for c in row.cells]
                    if any(cells):
                        paras.append(" | ".join(cells))
            return {"ok": True, "text": "\n".join(paras), "engine": "python-docx", "name": name}
        except Exception as e:
            return {"ok": False, "error": f"Word 解析失败：{e}"}
    if ext == ".pdf":
        try:
            import pypdf
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(data))
            pages = []
            for pg in reader.pages:
                pages.append(pg.extract_text() or "")
            text = "\n".join(pages).strip()
            if text:
                return {"ok": True, "text": text, "engine": "pypdf", "name": name}
            return {"ok": False, "error": "该 PDF 为扫描件/图片型，未提取到文字，请转成 Word 或图片后用 OCR"}
        except ImportError:
            return {"ok": False, "error": "未安装 PDF 解析组件（pypdf），请转成 Word/文本或图片"}
        except Exception as e:
            return {"ok": False, "error": f"PDF 解析失败：{e}"}
    if ext in (".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"):
        try:
            from . import media
            r = media.ocr_image(data)
            if r.get("ok"):
                return {"ok": True, "text": r.get("text", ""), "engine": r.get("engine", "OCR"), "name": name}
            return {"ok": False, "error": r.get("error", "OCR 失败")}
        except Exception as e:
            return {"ok": False, "error": f"OCR 失败：{e}"}
    return {"ok": False, "error": f"暂不支持 {ext or '该'} 类型，支持 docx/pdf/md/txt/图片"}


def save_upload_to_vault(name: str, data: bytes, folder: str = "材料") -> str:
    """把上传的原始文件保存到档案库指定目录，返回相对路径。"""
    from .config import VAULT_DIR
    import re
    safe = re.sub(r'[\\/:*?"<>|]', "_", name).strip() or "未命名文件"
    target_dir = VAULT_DIR / folder
    target_dir.mkdir(parents=True, exist_ok=True)
    p = target_dir / safe
    n = 1
    while p.exists():
        p = target_dir / f"{Path(safe).stem}_{n}{Path(safe).suffix}" if "." in safe else target_dir / f"{safe}_{n}"
        n += 1
    p.write_bytes(data)
    vault.scan_file(p)
    return vault.rel(p)


def build_prompt(session: dict, question: str, refs: list[str],
                 docs: list[dict]) -> tuple[list[dict], list[dict]]:
    cfg = _cfg()
    system = session.get("system_prompt") or cfg["system_prompt"] or DEFAULT_SYSTEM
    evidence: list[dict] = []

    # 1) 本地法律库检索（自动）
    try:
        law_hits = lawlib.retrieve(question, top_k=5)
    except Exception:
        law_hits = []
    if law_hits:
        ctx = "\n\n".join(f"[{e['law']}·{e['article']}] {e['text']}" for e in law_hits)
        system += LAW_GUIDANCE + f"\n\n《本地法律库摘录》\n{ctx}"
        evidence += [{"law": e["law"], "article": e["article"], "text": e["text"]} for e in law_hits]

    # 2) 档案库全文检索（自动）
    try:
        vault_hits = vault.search(question)[:5]
    except Exception:
        vault_hits = []
    if vault_hits:
        vctx = "\n\n".join(f"[{h['rel_path']}] {h.get('snippet','')}" for h in vault_hits)
        system += f"\n\n《本地档案库相关文档》\n{vctx}"
        evidence += [{"law": "档案库", "article": h["rel_path"], "text": h.get("snippet", "")}
                     for h in vault_hits]

    # 3) 用户挂载的本地文档
    if refs:
        text, metas = _context_from_refs(refs)
        if text:
            system += f"\n\n【用户挂载的本地资料】\n{text}"
            evidence += [{"law": "资料", "article": m["title"], "text": m["path"]} for m in metas]

    # 4) 用户上传的文档（本次对话）
    if docs:
        parts = []
        for d in docs:
            name = d.get("name", "文档")
            text = (d.get("text") or "")[:8000]
            parts.append(f"### 上传文档：{name}\n{text}")
        system += "\n\n【用户上传的文档】\n" + "\n\n".join(parts)
        evidence += [{"law": "上传文档", "article": d.get("name", "文档"), "text": ""} for d in docs]

    msgs = [{"role": "system", "content": system}]
    hist = messages(session["id"])[-cfg["max_context_messages"] * 2:]
    for m in hist:
        if m["role"] in ("user", "assistant"):
            msgs.append({"role": m["role"], "content": m["content"]})
    msgs.append({"role": "user", "content": question})
    return msgs, evidence


# ---------------- 流式调用 ----------------
def _stream_ollama(url: str, payload: dict, key: str, timeout: float) -> Iterator[str]:
    payload = dict(payload); payload["stream"] = True
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    if key:
        req.add_header("Authorization", f"Bearer {key}")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for line in resp:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line.decode("utf-8"))
            except Exception:
                continue
            chunk = ((obj.get("message") or {}).get("content")) or obj.get("response") or ""
            if chunk:
                yield chunk
            if obj.get("done"):
                break


def _stream_openai(url: str, payload: dict, key: str, timeout: float) -> Iterator[str]:
    payload = dict(payload); payload["stream"] = True
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "text/event-stream")
    if key:
        req.add_header("Authorization", f"Bearer {key}")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for line in resp:
            line = line.strip()
            if not line or not line.startswith(b"data:"):
                continue
            raw = line[5:].strip()
            if raw == b"[DONE]":
                break
            try:
                obj = json.loads(raw.decode("utf-8"))
            except Exception:
                continue
            delta = ((obj.get("choices") or [{}])[0].get("delta") or {}).get("content")
            if delta:
                yield delta


def stream_answer(session_id: int, question: str, refs: list[str] | None = None,
                  docs: list[dict] | None = None, model: str | None = None) -> Iterator[dict]:
    """生成器：yield {"type":"meta"/"delta"/"done"/"error", ...}。"""
    cfg = _cfg()
    session = get_session(session_id)
    model = model or session.get("model") or cfg["model"]
    mode = "assistant"

    db.execute("INSERT INTO ai_messages(session_id,role,content,evidence,model,mode,created)"
               " VALUES(?,?,?,?,?,?,?)",
               (session_id, "user", question, "", model, mode, db.now()))

    msgs, evidence = build_prompt(session, question, refs or [], docs or [])
    yield {"type": "meta", "mode": mode, "model": model,
           "evidence": evidence, "session_id": session_id}

    spec = PROVIDERS.get(cfg["provider"], PROVIDERS["ollama"])
    url = cfg["base_url"] + spec["path"]
    payload = {"model": model, "messages": msgs,
               "options": {"temperature": cfg["temperature"]},
               "temperature": cfg["temperature"]}
    key = api_key()
    buf: list[str] = []
    t0 = time.time()
    try:
        gen = _stream_openai(url, payload, key, cfg["timeout"]) if spec["openai_style"] \
            else _stream_ollama(url, payload, key, cfg["timeout"])
        for chunk in gen:
            buf.append(chunk)
            yield {"type": "delta", "text": chunk}
    except urllib.error.HTTPError as e:
        yield {"type": "error", "error": f"模型服务 HTTP {e.code}：{e.reason}"}
        return
    except Exception as e:
        yield {"type": "error", "error": f"模型服务不可用：{e}"}
        return

    answer = "".join(buf).strip()
    if not answer:
        answer = "（模型未返回内容，请确认模型已拉取且服务可访问；未装模型时仍可检索本地法律库与档案库）"
    db.execute("INSERT INTO ai_messages(session_id,role,content,evidence,model,mode,created)"
               " VALUES(?,?,?,?,?,?,?)",
               (session_id, "assistant", answer,
                json.dumps(evidence, ensure_ascii=False), model, mode, db.now()))
    db.execute("UPDATE ai_sessions SET updated=?, model=?, mode=? WHERE id=?",
               (db.now(), model, mode, session_id))
    if session.get("title") in ("新对话", "", None):
        db.execute("UPDATE ai_sessions SET title=? WHERE id=?",
                   (question[:28] or "新对话", session_id))
    db.audit("AI对话", f"{model} {len(answer)}字 {time.time()-t0:.1f}s")
    yield {"type": "done", "text": answer, "elapsed": round(time.time() - t0, 2)}


# ---------------- 快捷动作 ----------------
QUICK_ACTIONS = [
    {"key": "summary", "label": "归纳要点", "prompt": "请归纳以下内容的要点（5 条以内，结论先行）：\n\n"},
    {"key": "contract_review", "label": "合同风险审查", "prompt": "请审查以下合同，指出风险条款与修改建议（按条款逐项）：\n\n"},
    {"key": "timeline", "label": "梳理时间线", "prompt": "请把以下内容整理为按时间排序的事实时间线：\n\n"},
    {"key": "issue", "label": "提炼争议焦点", "prompt": "请提炼本案可能的争议焦点，并说明各方举证责任：\n\n"},
    {"key": "rewrite", "label": "改写为法言法语", "prompt": "请把以下内容改写为规范、严谨的法律文书表述：\n\n"},
    {"key": "risk", "label": "风险提示", "prompt": "请指出以下内容中的法律风险与应对建议：\n\n"},
]


def quick_actions() -> list[dict]:
    return QUICK_ACTIONS


def one_shot(question: str, system: str = "", timeout: float = 8.0) -> dict:
    """一次性同步补全（供内部功能调用，如案由 AI 把关），不写入会话。"""
    cfg = _cfg()
    spec = PROVIDERS.get(cfg["provider"], PROVIDERS["ollama"])
    url = cfg["base_url"] + spec["path"]
    msgs = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.append({"role": "user", "content": question})
    payload = {"model": cfg["model"], "messages": msgs,
               "options": {"temperature": 0.1}, "temperature": 0.1}
    key = api_key()
    try:
        gen = _stream_openai(url, payload, key, timeout) if spec["openai_style"] \
            else _stream_ollama(url, payload, key, timeout)
        text = "".join(gen).strip()
        return {"ok": True, "text": text}
    except Exception as e:
        return {"ok": False, "error": f"{e}"}


def save_settings(patch: dict) -> dict:
    cfg = load_config()
    ai = cfg.setdefault("ai", {})
    for k in ("provider", "base_url", "model", "temperature", "max_context_messages",
              "system_prompt", "strict_law_only", "timeout"):
        if k in patch:
            ai[k] = patch[k]
    if patch.get("api_key"):
        if not SECRETS.available:
            raise RuntimeError("加密组件不可用，为防泄露已拒绝保存 API Key")
        ai["api_key_enc"] = SECRETS.encrypt(patch["api_key"])
    ai.pop("api_key", None)
    from .config import save_config
    save_config(cfg)
    return {"ok": True, "status": status(), "providers": [{"key": k, "label": v["label"]}
                                                          for k, v in PROVIDERS.items()]}
