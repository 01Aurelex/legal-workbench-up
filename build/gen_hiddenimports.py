# -*- coding: utf-8 -*-
"""扫描后端源码的全部 import，生成 PyInstaller 需要的 hiddenimports 列表。

原因：业务模块被 Cython 编译为原生扩展后，PyInstaller 无法静态分析其中的
import 语句，必须显式声明，否则运行时报 ModuleNotFoundError。
"""
from __future__ import annotations

# --------------------------------------------------------------------------
# 路径解析：默认值全部相对「本脚本所在仓库」，可用 LW_* 环境变量覆盖。
#   LW_SRC    源码根目录（含 server/ frontend/ data/），默认仓库根
#   LW_BUILD  构建工作目录，默认本脚本所在目录（<repo>/build）
#   LW_DIST   免安装发行版目录（可选，仅作前端回退来源）
# --------------------------------------------------------------------------
import os as _os
_LW_BUILD = _os.path.dirname(_os.path.abspath(__file__))
_LW_ROOT = _os.path.dirname(_LW_BUILD)
_LW_BUILD_SRC = _os.path.join(_LW_BUILD, "src")
_LW_BUILD_OUT = _os.path.join(_LW_BUILD, "out")
_LW_DIST = _os.path.join(_LW_ROOT, "dist", "legal-workbench")

import ast
import os
import sys

SRC = os.environ.get("LW_SRC", _LW_ROOT)
ROOT = os.path.join(SRC, "server")

# 第三方/可选包：按需保留，缺失会被 PyInstaller 警告但不致命
THIRD_PARTY_HINT = {
    "docx", "openpyxl", "PIL", "pypdf", "cryptography", "requests", "yaml",
    "watchdog", "httpx", "aiohttp", "jinja2", "numpy", "fitz",
}

mods = set()
for dirpath, dirnames, filenames in os.walk(ROOT):
    dirnames[:] = [d for d in dirnames if d not in ("__pycache__",)]
    for fn in filenames:
        if not fn.endswith(".py"):
            continue
        path = os.path.join(dirpath, fn)
        try:
            tree = ast.parse(open(path, encoding="utf-8").read(), filename=path)
        except Exception:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    mods.add(a.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.level:            # 相对导入，跳过
                    continue
                if node.module:
                    mods.add(node.module.split(".")[0])

mods.discard("server")
mods.discard("__future__")
std = sorted(m for m in mods if m not in THIRD_PARTY_HINT)
third = sorted(m for m in mods if m in THIRD_PARTY_HINT)

print("# 标准库/内置 %d 个" % len(std))
for m in std:
    print("    %r," % m)
print("# 第三方 %d 个" % len(third))
for m in third:
    print("    %r," % m)
