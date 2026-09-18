# -*- coding: utf-8 -*-
# --------------------------------------------------------------------------
# 路径解析：默认值全部相对「本脚本所在仓库」，可用 LW_* 环境变量覆盖。
# --------------------------------------------------------------------------
import os as _os
_LW_BUILD = _os.path.dirname(_os.path.abspath(__file__))
import os
import sys
import traceback

SRC = os.environ.get("LW_BUILD", _LW_BUILD)
SRC = os.path.join(SRC, "src")
sys.path.insert(0, SRC)
try:
    import server.app.main  # noqa
    print("IMPORT OK")
except Exception:
    print(traceback.format_exc())
