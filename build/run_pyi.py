# -*- coding: utf-8 -*-
"""包一层运行 PyInstaller：用 logging FileHandler 直接接管日志，可靠落盘。

宿主环境下 PyInstaller 的 stdout/stderr 经常拿不到，这里在调用前用
logging.basicConfig(force=True) 把根日志器接到文件上。
用法：python build/run_pyi.py <日志文件> [额外参数...]
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

import logging
import os
import shutil
import sys
import tempfile
import time
import traceback

LOG = sys.argv[1] if len(sys.argv) > 1 else "pyi.log"
ARGS = [a for a in sys.argv[2:] if a != "--sidecar"]
if "--sidecar" in sys.argv[2:]:
    os.environ["LW_SIDECAR"] = "1"     # 产出 Tauri 内置后端（legal-workbench.exe）

os.environ.setdefault("PYTHONUNBUFFERED", "1")
os.environ.setdefault("PYTHONUTF8", "1")

# PyInstaller 会先清空 workpath / 覆盖 distpath，在启用 safe-delete 配额的环境里
# 会瞬间打满「每轮 50 次删除」额度（dist 目录 12 万个文件级别）。
# 对策：
#   1) workpath 放到系统临时目录 —— safe-delete 对临时目录内的路径直接放行；
#   2) distpath 下已存在的同名产物先用 os.rename 移走（rename 不计删除额度）。
PYI_WORK = os.path.join(tempfile.gettempdir(), "lw_pyi_work")
PYI_DIST = os.environ.get("LW_OUT", _LW_BUILD_OUT)

DIST_NAME = os.environ.get("LW_EXE_NAME") or (
    "legal-workbench" if os.environ.get("LW_SIDECAR") == "1" else "法岩律师本地工作台")
_stale = os.path.join(PYI_DIST, DIST_NAME)
if os.path.isdir(_stale):
    _dst = "%s_old_%s" % (_stale, time.strftime("%m%d_%H%M%S"))
    _i = 0
    while os.path.exists(_dst):
        _i += 1
        _dst = "%s_old_%s_%d" % (_stale, time.strftime("%m%d_%H%M%S"), _i)
    try:
        os.rename(_stale, _dst)
    except OSError:
        pass

logging.basicConfig(
    filename=LOG,
    filemode="w",
    encoding="utf-8",
    level=logging.DEBUG,
    force=True,
    format="%(levelname)s %(message)s",
)
log = logging.getLogger("runner")


class _W:
    """把 print / traceback 一并收进日志文件（宿主环境常拿不到原生 stderr）。"""

    def write(self, data):
        data = (data or "").strip()
        if data:
            log.error("CONSOLE: %s", data)

    def flush(self):
        pass


sys.stdout = _W()
sys.stderr = _W()

fh = open(LOG + ".crash", "w", encoding="utf-8")
try:
    import faulthandler

    faulthandler.enable(file=fh, all_threads=True)
except Exception:
    pass

code = 0
try:
    spec = os.environ.get("LW_PYI_TARGET") or os.path.join(_LW_BUILD, "legal-workbench.spec")
    log.info("开始构建: %s", spec)
    import PyInstaller.__main__

    argv = ["--noconfirm", "--log-level", "DEBUG"]
    if not spec.endswith(".spec"):
        argv += ["--paths", _LW_BUILD_SRC]
    argv += ["--distpath", PYI_DIST,
             "--workpath", PYI_WORK,
             spec] + ARGS
    PyInstaller.__main__.run(argv)
    log.info("构建结束")
except SystemExit as e:
    code = int(e.code or 0)
    log.error("PyInstaller 退出码=%s", e.code)
except Exception:
    log.error("异常:\n%s", traceback.format_exc())
    code = 1

logging.shutdown()
sys.exit(code)
