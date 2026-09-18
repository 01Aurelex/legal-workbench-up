# -*- coding: utf-8 -*-
"""一键构建「Tauri 原生外壳内置后端」或「独立桌面端」。

固定顺序（顺序不能乱：prep 会清空源树，必须在 Cython 之前）：
  1) prep_src          准备源树（去授权 / 同步前端 / 注入守卫）
  2) cythonize_app     业务模块 → 原生扩展
  3) finalize_native   删除已编译模块的 .py，记录清单
  4) build_main_native 单独处理含 FastAPI 注解的 main.py
  5) run_pyi           PyInstaller 打包
  6) make_manifest     生成 HMAC 完整性清单

用法：
  python build/build_all.py [--sidecar]      # --sidecar 产出 legal-workbench.exe
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

import os
import subprocess
import sys
import time

BUILD = os.environ.get("LW_BUILD", _LW_BUILD)
PY = sys.executable
SIDECAR = "--sidecar" in sys.argv


class _Tee:
    """同时写控制台与 UTF-8 日志文件：控制台编码常把中文变成乱码，日志才是排查依据。"""

    def __init__(self, fh):
        self._fh = fh

    def write(self, s):
        try:
            sys.__stdout__.write(s)
            sys.__stdout__.flush()
        except Exception:
            pass
        try:
            self._fh.write(s)
            self._fh.flush()
        except Exception:
            pass
        return len(s)

    def flush(self):
        for f in (sys.__stdout__, self._fh):
            try:
                f.flush()
            except Exception:
                pass


_LOGF = open(os.path.join(BUILD, "_build_all.log"), "w", encoding="utf-8")
sys.stdout = _Tee(_LOGF)
print("build_all 启动：%s  sidecar=%s  python=%s" % (time.strftime("%F %T"), SIDECAR, PY), flush=True)

STEPS = [
    ("准备源树", "prep_src.py", []),
    ("Cython 编译业务模块", "cythonize_app.py", []),
    ("清理源码并记录清单", "finalize_native.py", []),
    ("原生化 main.py", "build_main_native.py", []),
    ("PyInstaller 打包", "run_pyi.py",
     [os.path.join(BUILD, "_pyi_build.log")] + (["--sidecar"] if SIDECAR else [])),
]

name = "legal-workbench" if SIDECAR else "法岩律师本地工作台"
out = os.path.join(BUILD, "out", name)

t0 = time.time()
for label, script, args in STEPS:
    print("\n==> %s（%s）" % (label, script), flush=True)
    r = subprocess.run([PY, "-X", "utf8", os.path.join(BUILD, script)] + args,
                       cwd=BUILD, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    tail = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()
    for line in tail[-8:]:
        print("    " + line)
    if r.returncode not in (0, 2):      # 2 = main.py 回退为源码，允许继续
        print("[失败] %s 退出码 %d" % (script, r.returncode))
        sys.exit(1)

print("\n==> 检查 WebSocket 残留（防止 __version__ 启动崩溃）", flush=True)
internal = os.path.join(out, "_internal")
if not os.path.isdir(internal):
    candidate = os.path.join(out, "Contents", "MacOS")
    internal = candidate if os.path.isdir(candidate) else internal

ws_residue = []
if os.path.isdir(internal):
    for root, dirs, files in os.walk(internal):
        for d in list(dirs):
            if d in ("websockets", "wsproto") or d.startswith(("websockets.", "wsproto.")):
                ws_residue.append(os.path.join(root, d))
                dirs.remove(d)
        for f in files:
            if f.startswith(("websockets", "wsproto")):
                ws_residue.append(os.path.join(root, f))
if ws_residue:
    for p in ws_residue:
        dst = p + ".__disabled"
        i = 0
        while os.path.exists(dst):
            i += 1
            dst = "%s.__disabled%d" % (p, i)
        try:
            os.rename(p, dst)
            print("    ! 已禁用残留: %s" % os.path.basename(p))
        except OSError as e:
            print("    ! 残留禁用失败: %s => %s" % (p, e))
else:
    print("    干净：_internal 内无 websockets / wsproto")

print("\n==> 生成完整性清单", flush=True)
r = subprocess.run([PY, "-X", "utf8", os.path.join(BUILD, "make_manifest.py"), internal],
                   cwd=BUILD, capture_output=True, text=True,
                   encoding="utf-8", errors="replace")
print("    " + ((r.stdout or "") + (r.stderr or "")).strip())

size = 0
for root, _d, files in os.walk(out):
    for f in files:
        try:
            size += os.path.getsize(os.path.join(root, f))
        except OSError:
            pass
print("\n构建完成：%s（%.1f MB，用时 %.0f 秒）" % (out, size / 1048576.0, time.time() - t0))
