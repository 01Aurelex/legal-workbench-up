# -*- coding: utf-8 -*-
"""收尾：删除已编译模块的 .py 源码与中间 .c，记录原生模块清单。

独立执行，避免与 Cython 编译步骤耦合（setup() 之后若被中断也能单独补做）。
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
import glob
import os
import shutil
import sys

WORK = os.environ.get("LW_BUILD", _LW_BUILD)
ARCHIVE = os.path.join(WORK, "_stripped_src", __import__("time").strftime("%m%d_%H%M%S"))
WORK = os.path.join(WORK, "src")
os.chdir(WORK)


def move_out(path: str) -> None:
    """把已编译的 .py / 中间 .c 移出发行树（只 rename，不消耗 safe-delete 删除配额）。"""
    if not os.path.isfile(path):
        return
    dst = os.path.join(ARCHIVE, path)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.exists(dst):
        return
    os.rename(path, dst)


dirs = [os.path.join("server", "app"), "server"]
built, pyleft = [], []
for d in dirs:
    for pyd in glob.glob(os.path.join(d, "*.pyd")) + glob.glob(os.path.join(d, "*.so")):
        base = os.path.basename(pyd)
        stem = base.split(".")[0]
        built.append(stem)
        move_out(os.path.join(d, stem + ".py"))
        for c in glob.glob(os.path.join(d, stem + ".c")):
            move_out(c)
    pyleft += [os.path.basename(p) for p in glob.glob(os.path.join(d, "*.py"))]

built = sorted(set(built))
with open(os.path.join(WORK, "..", "native_modules.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(built))

print("原生模块 %d 个: %s" % (len(built), ", ".join(built)))
print("仍为源码形态: %s" % ", ".join(sorted(set(pyleft))))

# setuptools 中间产物（含 .obj/.lib 等数百个文件）：同样只移不删
tmp = os.path.join(WORK, "build")
if os.path.isdir(tmp):
    dst = os.path.join(ARCHIVE, "_setuptools_build")
    i = 0
    while os.path.exists(dst):
        i += 1
        dst = os.path.join(ARCHIVE, "_setuptools_build_%d" % i)
    try:
        os.rename(tmp, dst)
        print("中间目录 build/ 已移出到 _stripped_src/")
    except OSError as e:
        print("中间目录移出失败（可忽略）: %s" % e)
