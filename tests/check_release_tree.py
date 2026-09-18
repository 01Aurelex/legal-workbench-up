# -*- coding: utf-8 -*-
"""发布前校验：确保这个"要上传到公开仓库的目录"里没有不该有的东西。

两部分：
  A. 密钥/私密物料扫描（默认执行）——私钥、签发后台、运行时数据、大体积产物；
  B. 发布源树校验（--tree build/src）——确认 prep_src.py 已把授权门禁剔除干净。

用法：
  python tests/check_release_tree.py                    # 只跑 A
  python tests/check_release_tree.py --tree build/src   # A + B（B 需先跑 build/prep_src.py）
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------- A. 密钥扫描

# 目录名/相对路径：这些路径绝不允许出现在要公开的目录树里
FORBIDDEN_PATHS = [
    "license-admin",
    "data/.secret.key",
    "data/.license",
    "data/.access_token",
    "data/workbench.sqlite3",
    "data/backend.log",
    "data/startup_error.log",
    "src-tauri/target",
    "build/out",
    "build/unified",
    "dist",
    "node_modules",
    ".git",
]

# 内容特征：命中即视为泄露私钥。
# 注意：模式本身用拼接构造，避免本文件被自己的规则匹配（否则扫描器永远报自己）。
_D = "-" * 5
SECRET_PATTERNS = [
    (re.escape(_D) + r"BEGIN [A-Z ]*PRIVATE KEY" + re.escape(_D), "PEM 私钥"),
    (re.escape(_D) + r"BEGIN OPENSSH PRIVATE KEY" + re.escape(_D), "OpenSSH 私钥"),
    (r"ssh-ed25519\s+AAAA[A-Za-z0-9+/]{20,}", "SSH 公钥（疑似个人身份信息）"),
    (r"AKIA[0-9A-Z]{16}", "AWS Access Key"),
    (r"ghp_[A-Za-z0-9]{36}", "GitHub Personal Access Token"),
]

# 已知会存放签发私钥、且已被 .gitignore 整体排除的区域。
# 落在这些区域内的私钥属于"本地物料"，只提示；落在这之外的私钥一律判定为泄露。
EXCLUDED_KEY_AREAS = (
    "license-admin",
    "build/issuer_pkg",
    "build/issuer_work",
    "build/issuer_dist",
)

# 只扫这些文本扩展名，避免把 docx/png 当文本读
TEXT_EXT = {".py", ".js", ".mjs", ".css", ".html", ".json", ".yml", ".yaml",
            ".toml", ".rs", ".md", ".txt", ".spec", ".plist", ".bat", ".cmd",
            ".ps1", ".iss", ".pem", ".key", ".cfg", ".ini", ".env"}

# 这些目录整个跳过（构建产物/依赖，扫了没意义还慢）
SKIP_DIRS = {"__pycache__", ".git", "node_modules", "target", "out", "unified",
             "dist", "_internal", "_scratch", ".venv", "venv", "env"}

fails: list[str] = []


def scan_secrets() -> None:
    print("== A. 密钥与私密物料扫描 ==")
    for rel in FORBIDDEN_PATHS:
        p = REPO / rel
        if p.exists():
            # 这些路径可能只是运行期产物，用 .gitignore 兜住即可 —— 但仓库里存在就必须提示
            print(f"  ! 存在（请确认已被 .gitignore 排除）: {rel}")
        else:
            print(f"  ok 不存在: {rel}")

    hits = 0
    scanned = 0
    self_path = Path(__file__).resolve()
    for cur, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fn in files:
            if os.path.splitext(fn)[1].lower() not in TEXT_EXT:
                continue
            p = Path(cur) / fn
            if p.resolve() == self_path:
                continue          # 不扫自己
            try:
                if p.stat().st_size > 4 * 1024 * 1024:
                    continue
                txt = p.read_text(encoding="utf-8", errors="strict")
            except Exception:
                continue          # 二进制/非 UTF-8 直接跳过
            scanned += 1
            rel = p.relative_to(REPO).as_posix()
            excluded = any(rel == a or rel.startswith(a + "/") for a in EXCLUDED_KEY_AREAS)
            for pat, label in SECRET_PATTERNS:
                m = re.search(pat, txt)
                if not m:
                    continue
                hits += 1
                if excluded:
                    print(f"  ! {label}（位于已排除区域，不入库）: {rel}")
                else:
                    fails.append(f"发现{label}: {rel}  ({m.group(0)[:48]})")
                    print(f"  [FAIL] {label} {rel}")
    print(f"  已扫描文本文件 {scanned} 个，命中 {hits} 处")


# ---------------------------------------------------------------- B. 发布树校验

def check_release_tree(tree: str) -> None:
    print(f"\n== B. 发布源树校验: {tree} ==")
    root = (REPO / tree).resolve() if not Path(tree).is_absolute() else Path(tree)
    main_py = root / "server" / "app" / "main.py"
    if not main_py.is_file():
        fails.append(f"找不到 {main_py}，请先运行 python build/prep_src.py")
        print("  [FAIL] 源树不存在，请先运行 build/prep_src.py")
        return

    txt = main_py.read_text(encoding="utf-8")
    residues = [k for k in ("lic.", "license_gate", "/api/license/", "license.py")
                if k in txt]
    if residues:
        fails.append(f"发布源树仍残留授权门禁: {residues}")
        print(f"  [FAIL] main.py 仍含 {residues}")
    else:
        print("  ok main.py 已无授权门禁（lic. / license_gate / /api/license/）")

    # 授权模块本身不应被复制进发布树
    if (root / "server" / "app" / "license.py").exists():
        fails.append("发布源树仍含 server/app/license.py")
        print("  [FAIL] 仍存在 server/app/license.py")
    else:
        print("  ok 未复制 server/app/license.py")

    # 运行时数据不应混入
    for rel in ("data/.secret.key", "data/workbench.sqlite3", "data/.license"):
        if (root / rel).exists():
            print(f"  ! 发布树含运行期文件（打包前需清理）: {rel}")

    # 必要素材必须到位
    need = ["frontend/index.html", "data/law_library", "data/templates", "server/guard.py"]
    for rel in need:
        ok = (root / rel).exists()
        print(("  ok " if ok else "  [FAIL] 缺少 ") + rel)
        if not ok:
            fails.append(f"发布源树缺少 {rel}")


# ---------------------------------------------------------------- main

if __name__ == "__main__":
    scan_secrets()
    tree = None
    if "--tree" in sys.argv:
        i = sys.argv.index("--tree") + 1
        if i < len(sys.argv):
            tree = sys.argv[i]
    if tree:
        check_release_tree(tree)

    print("\n" + "=" * 60)
    if fails:
        print(f"校验未通过，共 {len(fails)} 项：")
        for f in fails:
            print("  - " + f)
        sys.exit(1)
    print("校验通过：未发现私钥泄露，发布源树干净。")
