# -*- coding: utf-8 -*-
"""本地法律库：扫描 data/law_library 下 Markdown，按“第X条”切块，纯本地中文二元组检索。
AI 答复只能引用本库内容（需求8），并在库陈旧/缺失时提醒更新（需求9）。"""
from __future__ import annotations
import re
from datetime import datetime, timedelta
from pathlib import Path

from .config import LAWLIB_DIR
from . import db

ART_RE = re.compile(r"(第[一二三四五六七八九十百千万零〇0-9]+条[之\-\d]*)\s*")
HEAD_RE = re.compile(r"^#{1,3}\s+(.+)$", re.M)
STOP = set("的了和是在我你他她它们与及或而且但对为中由以就都也就并被把让给个之与其等")


def _bigrams(text: str) -> tuple[list[str], list[str]]:
    """返回(单字表, 二元组表)；相关性判定以二元组为主，避免单字共同词造成弱匹配。"""
    text = re.sub(r"[\s\W_0-9a-zA-Z]+", "", text)
    uni = [ch for ch in text if ch not in STOP]
    bi = [text[i:i + 2] for i in range(len(text) - 1)]
    return uni, bi


def chunk_law_text(name: str, text: str) -> list[dict]:
    """按第X条切分；无条号的文件按 800 字滑窗切块。"""
    chunks = []
    matches = list(ART_RE.finditer(text))
    if matches:
        for i, m in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            body = text[m.start():end].strip()
            art = m.group(1)
            if len(body) >= 8:
                chunks.append({"law": name, "article": art, "text": body[:2000]})
    else:
        s = re.sub(r"^#{1,3}.*$", "", text, flags=re.M).strip()
        for i in range(0, len(s), 800):
            chunks.append({"law": name, "article": f"段落{i//800+1}", "text": s[i:i+800]})
    return chunks


def build_index(force: bool = False) -> dict:
    cached = db.kv_get("lawlib_index")
    files = sorted(LAWLIB_DIR.glob("*.md"))
    sig = ";".join(f"{f.name}:{f.stat().st_mtime_ns}" for f in files)
    if cached and not force and cached.get("sig") == sig:
        return {"chunks": len(cached.get("chunks", [])), "cached": True}
    chunks = []
    law_names = []
    for f in files:
        text = f.read_text(encoding="utf-8")
        hm = HEAD_RE.search(text)
        name = hm.group(1).strip() if hm else f.stem
        law_names.append(name)
        chunks.extend(chunk_law_text(name, text))
    for c in chunks:
        c["uni"], c["bi"] = _bigrams(c["text"])
    db.kv_set("lawlib_index", {"sig": sig, "chunks": chunks,
                               "laws": law_names, "built": db.now()})
    return {"chunks": len(chunks), "cached": False, "laws": law_names}


def _score(q_grams: list[str], c_grams: list[str]) -> float:
    if not c_grams:
        return 0.0
    cset = set(c_grams)
    hit = sum(1 for g in q_grams if g in cset)
    if hit == 0:
        return 0.0
    return hit / (len(q_grams) ** 0.5 * len(cset) ** 0.5)


def retrieve(question: str, top_k: int = 5) -> list[dict]:
    build_index()
    chunks = db.kv_get("lawlib_index", {}).get("chunks", [])
    q_uni, q_bi = _bigrams(question)
    q_bi_set = set(q_bi)
    scored = []
    for i, c in enumerate(chunks):
        cset = set(c.get("uni", [])) | set(c.get("bi", []))
        if not cset:
            continue
        hit = sum(1 for g in q_uni + q_bi if g in cset)
        if hit == 0:
            continue
        bi_hit = len(q_bi_set & set(c.get("bi", [])))
        bi_ratio = bi_hit / len(q_bi_set) if q_bi_set else 0
        score = hit / ((len(q_uni) + len(q_bi)) ** 0.5 * len(cset) ** 0.5)
        # 以二元组词覆盖率为主阈值，杜绝“火星移民”这类问题被共同单字弱匹配
        if bi_ratio >= 0.34 and score >= 0.06:
            scored.append((score, i))
    scored.sort(reverse=True)
    out = []
    for score, i in scored[:top_k]:
        c = chunks[i]
        out.append({"law": c["law"], "article": c["article"],
                    "text": c["text"], "score": round(score, 4)})
    return out


def status() -> dict:
    idx = db.kv_get("lawlib_index")
    files = list(LAWLIB_DIR.glob("*.md"))
    built = idx.get("built") if idx else None
    remind_days = 90
    reminders = []
    if not files:
        reminders.append("本地法律库为空，请导入法律法规 Markdown/TXT 后建立索引。")
    if not built:
        reminders.append("法律库尚未建立索引。")
    else:
        try:
            bdt = datetime.strptime(built, "%Y-%m-%d %H:%M:%S")
            age = (datetime.now() - bdt).days
            if age > remind_days:
                reminders.append(f"法律库索引已 {age} 天未更新，建议核对新法与修正情况后重建索引。")
        except Exception:
            pass
    return {"law_files": len(files), "chunks": len(idx["chunks"]) if idx else 0,
            "built": built, "laws": (idx or {}).get("laws", []), "reminders": reminders}
