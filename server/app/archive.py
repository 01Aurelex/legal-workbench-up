# -*- coding: utf-8 -*-
"""档案库：文件树、总体管理表格（多维表格）、本地打开/定位/重命名/删除。

安全约束：所有路径必须落在 VAULT_DIR 或 INVOICE_DIR 之内，越界一律拒绝。
"""
from __future__ import annotations
import hashlib
import os
import platform
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from .config import VAULT_DIR, DATA_DIR
from . import db, vault

INVOICE_DIR = DATA_DIR / "invoices"

CATEGORY_MAP = {"客户": "客户", "案件": "案件", "材料": "材料",
                "文书": "文书", "笔记": "笔记"}

# 允许在总表中出现的文件后缀（二进制大文件也登记，便于统一检索）
SCAN_EXT = {".md", ".txt", ".docx", ".doc", ".pdf", ".xlsx", ".xls", ".pptx",
            ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".webp",
            ".zip", ".rar", ".7z", ".ofd", ".csv", ".eml", ".msg", ".wav", ".mp3", ".mp4"}


def _safe_path(rel_path: str) -> Path:
    """把相对路径解析为绝对路径，强制限制在允许的两个根目录内。"""
    p = (VAULT_DIR / rel_path).resolve()
    if VAULT_DIR.resolve() in p.parents or p == VAULT_DIR.resolve():
        return p
    q = (INVOICE_DIR / rel_path).resolve()
    if INVOICE_DIR.resolve() in q.parents or q == INVOICE_DIR.resolve():
        return q
    raise ValueError("路径越界，已拒绝访问")


def _rel_to_vault(p: Path) -> str:
    return p.relative_to(VAULT_DIR).as_posix()


# ---------------- 总表同步 ----------------
def sync_registry() -> dict:
    """扫描档案库目录，把全部文件登记进 doc_registry（多维表格数据源）。"""
    seen, added, updated = set(), 0, 0
    for p in VAULT_DIR.rglob("*"):
        if not p.is_file() or p.name.startswith("."):
            continue
        if p.suffix.lower() not in SCAN_EXT:
            continue
        rel = _rel_to_vault(p)
        seen.add(rel)
        st = p.stat()
        top = rel.split("/", 1)[0]
        existing = db.query_one("SELECT rel_path,size,mtime FROM doc_registry WHERE rel_path=?", (rel,))
        row = {
            "rel_path": rel,
            "title": p.stem,
            "category": CATEGORY_MAP.get(top, "其他"),
            "ext": p.suffix.lower(),
            "size": st.st_size,
            "mtime": st.st_mtime,
            "updated": db.now(),
        }
        if existing is None:
            row.update({"client": "", "case_ref": "", "tags": "", "starred": 0,
                        "remark": "", "open_count": 0, "last_open": "",
                        "created": datetime.fromtimestamp(st.st_ctime).strftime("%Y-%m-%d %H:%M:%S")})
            db.upsert("doc_registry", "rel_path", row)
            added += 1
        elif abs((existing["mtime"] or 0) - st.st_mtime) > 0.5 or existing["size"] != st.st_size:
            db.upsert("doc_registry", "rel_path", row)
            updated += 1
    for r in db.query("SELECT rel_path FROM doc_registry"):
        if r["rel_path"] not in seen and not (VAULT_DIR / r["rel_path"]).exists():
            db.execute("DELETE FROM doc_registry WHERE rel_path=?", (r["rel_path"],))
    _auto_bind()
    return {"total": len(seen), "added": added, "updated": updated}


def _bind_for_rel(rel: str) -> tuple[str, str]:
    """依据已有案件/客户，推断一份档案应绑定的客户与案件（目录名/路径包含即命中）。"""
    parts = rel.split("/")
    client, case_ref = "", ""
    # 1) 精确命中「客户-案由」案件目录名
    for c in db.query("SELECT rel_path,client FROM cases"):
        stem = Path(c["rel_path"]).stem  # 客户-案由
        if stem and stem in rel:
            client, case_ref = c["client"] or "", stem
            break
    # 2) 命中客户名
    if not client:
        for c in db.query("SELECT DISTINCT client FROM cases WHERE client!=''"):
            if c["client"] and c["client"] in rel:
                client = c["client"]
                break
    # 3) 旧式目录约定：文书/<案件名>/…、材料/<客户-案由>/…（材料目录下仅"客户-案由"形态才算案件目录）
    if not case_ref and parts[0] in ("文书", "材料") and len(parts) >= 2:
        head = parts[1]
        is_case_dir = ("-" in head) or any(
            Path(c["rel_path"]).stem == head
            for c in db.query("SELECT rel_path FROM cases"))
        if is_case_dir:
            case_ref = head
    # 4) 案件目录下自身文件
    if parts[0] == "案件":
        c = db.query_one("SELECT client FROM cases WHERE rel_path=?", (rel,))
        if c:
            client, case_ref = c["client"] or "", Path(rel).stem
    return client, case_ref


def _auto_bind():
    """自动把文书/材料绑定到客户与案件（依据目录名与文件名前缀）。"""
    for r in db.query("SELECT rel_path,client,case_ref FROM doc_registry "
                      "WHERE client='' OR client IS NULL OR case_ref='' OR case_ref IS NULL"):
        rel = r["rel_path"]
        client, case_ref = _bind_for_rel(rel)
        client = client or (r["client"] or "")
        case_ref = case_ref or (r["case_ref"] or "")
        if client != (r["client"] or "") or case_ref != (r["case_ref"] or ""):
            db.execute("UPDATE doc_registry SET client=?, case_ref=? WHERE rel_path=?",
                       (client, case_ref, rel))


# ---------------- 文件树 ----------------
def tree() -> list[dict]:
    roots = []
    for top in sorted(VAULT_DIR.iterdir()):
        if top.is_dir():
            roots.append(_node(top))
        elif top.is_file() and top.suffix.lower() in SCAN_EXT:
            roots.append({"name": top.name, "path": _rel_to_vault(top), "type": "file",
                          "ext": top.suffix.lower(), "size": top.stat().st_size,
                          "children": []})
    return roots


def _node(d: Path) -> dict:
    children = []
    try:
        entries = sorted(d.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
    except OSError:
        entries = []
    for e in entries:
        if e.name.startswith("."):
            continue
        if e.is_dir():
            children.append(_node(e))
        elif e.suffix.lower() in SCAN_EXT:
            children.append({"name": e.name, "path": _rel_to_vault(e), "type": "file",
                             "ext": e.suffix.lower(), "size": e.stat().st_size, "children": []})
    return {"name": d.name, "path": _rel_to_vault(d) if d != VAULT_DIR else "",
            "type": "dir", "children": children}


# ---------------- 多维表格 ----------------
def table_rows(keyword: str = "", category: str = "", client: str = "",
               starred: bool = False, sort: str = "updated", desc: bool = True,
               limit: int = 1000) -> list[dict]:
    sql = "SELECT * FROM doc_registry WHERE 1=1"
    args: list = []
    if category:
        sql += " AND category=?"; args.append(category)
    if client:
        sql += " AND client=?"; args.append(client)
    if starred:
        sql += " AND starred=1"
    if keyword:
        sql += " AND (title LIKE ? OR rel_path LIKE ? OR tags LIKE ? OR remark LIKE ? OR client LIKE ?)"
        args += [f"%{keyword}%"] * 5
    allowed = {"updated", "created", "last_open", "open_count", "size", "title", "mtime", "category"}
    order = sort if sort in allowed else "updated"
    sql += f" ORDER BY {order} {'DESC' if desc else 'ASC'} LIMIT ?"
    args.append(limit)
    return db.query(sql, tuple(args))


def update_fields(rel_path: str, patch: dict) -> dict:
    row = db.query_one("SELECT * FROM doc_registry WHERE rel_path=?", (rel_path,))
    if not row:
        raise ValueError("档案不存在")
    fields = ("title", "category", "client", "case_ref", "tags", "remark", "starred")
    sets, args = [], []
    for f in fields:
        if f in patch:
            val = patch[f]
            if f == "starred":
                val = 1 if val else 0
            elif isinstance(val, str):
                val = val.strip()
            sets.append(f"{f}=?"); args.append(val)
    if sets:
        args.append(rel_path)
        db.execute(f"UPDATE doc_registry SET {','.join(sets)}, updated=? WHERE rel_path=?",
                   tuple(args[:-1] + [db.now(), rel_path]))
    return db.query_one("SELECT * FROM doc_registry WHERE rel_path=?", (rel_path,))


# ---------------- 本地操作 ----------------
def _open_with_system(path: Path) -> dict:
    path = Path(path)
    if not path.exists():
        return {"ok": False, "error": "文件不存在"}
    try:
        sysname = platform.system()
        if sysname == "Windows":
            os.startfile(str(path))  # noqa: S606
        elif sysname == "Darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
        return {"ok": True, "opened": str(path)}
    except Exception as e:
        return {"ok": False, "error": f"打开失败：{e}"}


def open_local(rel_path: str, record: bool = True) -> dict:
    """用本机默认程序打开档案（右键→打开本地文档）。"""
    p = _safe_path(rel_path)
    res = _open_with_system(p)
    if res.get("ok") and record:
        db.execute("UPDATE doc_registry SET open_count=COALESCE(open_count,0)+1, last_open=? "
                   "WHERE rel_path=?", (db.now(), rel_path))
        db.audit("打开本地文档", rel_path)
    return res


def reveal(rel_path: str) -> dict:
    """在文件管理器中定位到该档案。"""
    p = _safe_path(rel_path)
    target = p if p.is_dir() else p.parent
    try:
        if platform.system() == "Windows":
            subprocess.Popen(["explorer", "/select,", str(p)] if p.is_file()
                             else ["explorer", str(target)])
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", "-R", str(p)] if p.is_file() else ["open", str(target)])
        else:
            subprocess.Popen(["xdg-open", str(target)])
        return {"ok": True, "path": str(target)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def open_folder(rel_dir: str = "") -> dict:
    d = _safe_path(rel_dir) if rel_dir else VAULT_DIR
    if not d.is_dir():
        d = d.parent
    try:
        if platform.system() == "Windows":
            os.startfile(str(d))  # noqa: S606
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", str(d)])
        else:
            subprocess.Popen(["xdg-open", str(d)])
        return {"ok": True, "path": str(d)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def rename(rel_path: str, new_name: str) -> dict:
    p = _safe_path(rel_path)
    new_name = (new_name or "").strip().strip("/\\")
    if not new_name:
        raise ValueError("新名称不能为空")
    target = p.parent / new_name
    if target.exists():
        raise ValueError("同名文件已存在")
    p.rename(target)
    db.execute("DELETE FROM doc_registry WHERE rel_path=?", (rel_path,))
    if p.suffix.lower() == ".md":
        db.execute("DELETE FROM files WHERE rel_path=?", (rel_path,))
        db.execute("DELETE FROM links WHERE src=?", (rel_path,))
    db.audit("重命名档案", f"{rel_path} -> {new_name}")
    sync_registry()
    vault.scan_vault()
    return {"ok": True, "path": _rel_to_vault(target) if VAULT_DIR in target.parents else new_name}


def delete(rel_path: str) -> dict:
    p = _safe_path(rel_path)
    if p.is_dir():
        shutil.rmtree(p)
        db.execute("DELETE FROM doc_registry WHERE rel_path LIKE ?", (rel_path + "/%",))
    else:
        p.unlink()
        db.execute("DELETE FROM doc_registry WHERE rel_path=?", (rel_path,))
        if p.suffix.lower() == ".md":
            db.execute("DELETE FROM files WHERE rel_path=?", (rel_path,))
            db.execute("DELETE FROM links WHERE src=?", (rel_path,))
            db.execute("DELETE FROM cases WHERE rel_path=?", (rel_path,))
    db.audit("删除档案", rel_path)
    return {"ok": True}


def new_folder(parent: str, name: str) -> dict:
    base = _safe_path(parent) if parent else VAULT_DIR
    name = (name or "").strip().strip("/\\")
    if not name:
        raise ValueError("文件夹名不能为空")
    d = base / name
    d.mkdir(parents=True, exist_ok=True)
    return {"ok": True, "path": _rel_to_vault(d)}


def save_upload(rel_dir: str, filename: str, data: bytes) -> dict:
    base = _safe_path(rel_dir) if rel_dir else VAULT_DIR
    base.mkdir(parents=True, exist_ok=True)
    name = "".join(c for c in (filename or "未命名") if c not in '\\/:*?"<>|').strip() or "未命名"
    target = base / name
    n = 1
    while target.exists():
        stem, ext = Path(name).stem, Path(name).suffix
        target = base / f"{stem}_{n}{ext}"
        n += 1
    target.write_bytes(data)
    db.audit("上传档案", str(target))
    sync_registry()
    return {"ok": True, "path": _rel_to_vault(target), "name": target.name,
            "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def detail(rel_path: str) -> dict:
    p = _safe_path(rel_path)
    st = p.stat()
    row = db.query_one("SELECT * FROM doc_registry WHERE rel_path=?", (rel_path,)) or {}
    return {"path": rel_path, "name": p.name, "abs": str(p),
            "size": st.st_size, "ext": p.suffix.lower(),
            "created": datetime.fromtimestamp(st.st_ctime).strftime("%Y-%m-%d %H:%M:%S"),
            "modified": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            "row": row}


# ---------------- 一键导入：扫描指定外部文件夹并智能归档 ----------------
def _safe_name(name: str) -> str:
    return "".join(c for c in (name or "未命名") if c not in '\\/:*?"<>|').strip() or "未命名"


def _dedup_target(target: Path) -> Path:
    """目标重名时自动加 _1/_2 后缀。"""
    if not target.exists():
        return target
    stem, ext, n = target.stem, target.suffix, 1
    while True:
        cand = target.with_name(f"{stem}_{n}{ext}")
        if not cand.exists():
            return cand
        n += 1


def import_folder(src: str, move: bool = False) -> dict:
    """递归扫描外部文件夹，把可管理文件复制（或移动）进档案库并智能匹配客户/案件。

    归档规则：
    - 路径/文件名命中已有「客户-案由」案件 → 材料/<客户-案由>/ 下，保留原子目录结构；
    - 仅命中客户名 → 材料/<客户名>/；
    - 其余 → 材料/外部导入/<源文件夹名>/。
    """
    root = Path(src).expanduser()
    if not root.exists() or not root.is_dir():
        raise ValueError("文件夹不存在或不是目录")
    root_res = root.resolve()
    vault_res = VAULT_DIR.resolve()
    if root_res == vault_res or vault_res in root_res.parents:
        raise ValueError("不能导入档案库自身目录，请选择其他文件夹")

    # 案件/客户匹配表
    def _cause_core(cause: str) -> str:
        """去掉案由常见后缀作为核心匹配词，如 离婚协议纠纷→离婚协议、劳动争议→劳动。"""
        cause = (cause or "").strip()
        for suf in ("纠纷", "争议", "案件", "诉讼"):
            if len(cause) > len(suf) + 1 and cause.endswith(suf):
                return cause[:-len(suf)]
        return cause

    case_rows = []  # (案件目录名, 客户, 案由核心词)
    for c in db.query("SELECT rel_path,client,cause FROM cases"):
        case_rows.append((Path(c["rel_path"]).stem, c["client"] or "", _cause_core(c.get("cause") or "")))
    clients = [c["client"] for c in db.query("SELECT DISTINCT client FROM cases WHERE client!=''")]

    imported, unsupported, duplicates, matched_case, matched_client = [], [], [], 0, 0
    total = 0
    for f in sorted(root.rglob("*")):
        if not f.is_file() or f.name.startswith("."):
            continue
        total += 1
        rel_sub = f.relative_to(root).as_posix()
        hay = f"{root.name}/{rel_sub}"
        ext = f.suffix.lower()
        if ext not in SCAN_EXT:
            unsupported.append({"name": rel_sub, "reason": f"不支持的类型 {ext or '无后缀'}"})
            continue
        # 智能匹配归属：①完整案件目录名 ②客户名+案由核心词同时命中 ③案由核心词唯一命中 ④仅客户名
        stem_hit, client_hit = "", ""
        for stem, client, _core in case_rows:
            if stem and stem in hay:
                stem_hit, client_hit = stem, client
                break
        if not stem_hit:
            for stem, client, core in case_rows:
                if client and client in hay and len(core) >= 2 and core in hay:
                    stem_hit, client_hit = stem, client
                    break
        if not stem_hit:
            cand = [(stem, client) for stem, _c, core in case_rows
                    if len(core) >= 2 and core in hay]
            if len(cand) == 1:
                stem_hit, client_hit = cand[0]
        if not stem_hit:
            for name in clients:
                if name and name in hay:
                    client_hit = name
                    break
        if stem_hit:
            dest_dir = VAULT_DIR / "材料" / stem_hit / f.relative_to(root).parent
            matched_case += 1
        elif client_hit:
            dest_dir = VAULT_DIR / "材料" / _safe_name(client_hit) / f.relative_to(root).parent
            matched_client += 1
        else:
            dest_dir = VAULT_DIR / "材料" / "外部导入" / _safe_name(root.name) / f.relative_to(root).parent
        dest_dir.mkdir(parents=True, exist_ok=True)
        raw_target = dest_dir / _safe_name(f.name)
        try:
            if raw_target.exists() and raw_target.stat().st_size == f.stat().st_size:
                duplicates.append({"name": rel_sub, "reason": "目标已存在同名同大小文件，已跳过"})
                continue
            target = _dedup_target(raw_target)
            if move:
                shutil.move(str(f), str(target))
            else:
                shutil.copy2(str(f), str(target))
        except Exception as e:  # 单文件失败不中断整批
            unsupported.append({"name": rel_sub, "reason": f"复制失败：{e}"})
            continue
        imported.append({"name": rel_sub, "dest": _rel_to_vault(target),
                         "bind": "案件" if stem_hit else ("客户" if client_hit else "待归类")})

    vault.scan_vault()
    reg = sync_registry()
    db.audit("一键导入文件夹", f"{root} → 导入{len(imported)} 跳过{len(unsupported) + len(duplicates)}")
    return {"ok": True, "source": str(root), "total": total,
            "imported_count": len(imported), "unsupported_count": len(unsupported),
            "duplicate_count": len(duplicates),
            "matched_case": matched_case, "matched_client": matched_client,
            "imported": imported[:500], "unsupported": unsupported[:200],
            "duplicates": duplicates[:200], "registry": reg, "moved": bool(move)}
