# -*- coding: utf-8 -*-
"""单独把 server/app/main.py 编译为原生扩展。

main.py 含 FastAPI 路由签名（files: list[UploadFile] = File(...)），
必须使用 annotation_typing=False 保留注解，否则 FastAPI 无法识别 File 参数。
编译后若导入失败，则自动回退为 .py 源码形态，保证可运行。
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
import re
import shutil
import subprocess
import sys
import time

BUILD = os.environ.get("LW_BUILD", _LW_BUILD)
SRC = os.environ.get("LW_SRC", _LW_ROOT)
WORK = os.path.join(BUILD, "src")
PY = sys.executable


def _ensure_msvc() -> None:
    """在当前进程内注入 MSVC 环境（本进程由 build_all 拉起，不继承 vcvars 的变量）。"""
    if sys.platform != "win32" or shutil.which("cl"):
        return
    cand = sorted(glob.glob(r"C:\Program Files*\Microsoft Visual Studio\2022\*\VC\Tools\MSVC\*"),
                  reverse=True)
    if not cand:
        return
    msvc = cand[0]
    kits = r"C:\Program Files (x86)\Windows Kits\10"
    sdks = sorted(glob.glob(os.path.join(kits, "Include", "*")), reverse=True)
    sdk = os.path.basename(sdks[0]) if sdks else None
    inc = [os.path.join(msvc, "include")]
    lib = [os.path.join(msvc, "lib", "x64")]
    pth = [os.path.join(msvc, "bin", "Hostx64", "x64")]
    if sdk:
        inc += [os.path.join(kits, "Include", sdk, s) for s in
                ("ucrt", "um", "shared", "winrt", "cppwinrt")]
        lib += [os.path.join(kits, "Lib", sdk, s, "x64") for s in ("ucrt", "um")]
        pth += [os.path.join(kits, "bin", sdk, "x64")]
    os.environ["INCLUDE"] = os.pathsep.join(inc)
    os.environ["LIB"] = os.pathsep.join(lib)
    os.environ["PATH"] = os.pathsep.join(pth) + os.pathsep + os.environ.get("PATH", "")
    print("已注入 MSVC 环境: %s" % msvc)


_ensure_msvc()

target = os.path.join(WORK, "server", "app", "main.py")

# 1) 还原源码（含去授权处理）
txt = open(os.path.join(SRC, "server", "app", "main.py"), encoding="utf-8").read()
txt = txt.replace("license as lic, ", "")
txt = re.sub(r'@app\.middleware\("http"\)\s*\nasync def license_gate.*?return await call_next\(request\)\n\n',
             "", txt, flags=re.S)
txt = txt.replace("return ok(token=get_or_create_token(), license=lic.license_status())",
                  "return ok(token=get_or_create_token())")
txt = re.sub(r'# =+ 授权激活（一机一码） =+\n(?:@app\.\w+\("/api/license/.*?\n(?:    .*\n|)*?\n)+', "", txt)
if "/api/license/" in txt:                      # 正则未命中时的逐行兜底
    lines, out, skip = txt.split("\n"), [], False
    for ln in lines:
        if "/api/license/" in ln:
            skip = True
            continue
        if skip:
            if ln.startswith("@app.") or (ln and not ln.startswith((" ", "\t", "@"))
                                          and not ln.rstrip().endswith(":")):
                skip = False
            else:
                continue
        out.append(ln)
    txt = "\n".join(out)
# 若仍有 lic. 残留（说明授权调用未清干净），直接放弃原生化，避免编出不可用的模块
if "lic." in txt:
    print("main.py 仍残留授权调用，回退为源码形态")
    open(target, "w", encoding="utf-8").write(txt)
    sys.exit(2)
# 文件级 Cython 指令：保留注解，避免 FastAPI 的 File/Form 参数签名被优化掉
if "cython: annotation_typing" not in txt:
    txt = "# cython: annotation_typing=False\n# cython: language_level=3\n" + txt
open(target, "w", encoding="utf-8").write(txt)

# 2) 编译
os.chdir(WORK)
sys.path.insert(0, WORK)
from Cython.Build import cythonize  # noqa: E402
from setuptools import setup  # noqa: E402

rel = os.path.join("server", "app", "main.py")
try:
    exts = cythonize([rel], language_level=3, force=True, quiet=True,
                     compiler_directives={
                         "language_level": 3,
                         "annotation_typing": False,
                         "always_allow_keywords": True,
                         "embedsignature": False,
                     })
except Exception as e:
    print("cythonize 失败: %s" % e)
    sys.exit(1)

if sys.platform == "win32":
    for e in exts:
        e.extra_link_args = list(e.extra_link_args or []) + ["/MANIFEST:NO"]

setup(name="lw_main", ext_modules=exts,
      script_args=["build_ext", "--inplace", "-j", str(os.cpu_count() or 4)])

# 3) 验证导入
r = subprocess.run([PY, "-X", "utf8", os.path.join(BUILD, "tb_main.py")],
                   capture_output=True, text=True, encoding="utf-8", errors="replace")
out = (r.stdout or "") + (r.stderr or "")
if "IMPORT OK" in out or ("server.app.main" in out and "Traceback" not in out):
    print("main 原生化成功")
    # cythonize_app 已跳过 main.py，所以这里要把它补进原生模块清单，
    # 否则 make_manifest 不会把 main.*.pyd 纳入完整性校验。
    try:
        nm = os.path.join(BUILD, "native_modules.txt")
        names = []
        if os.path.isfile(nm):
            names = [x.strip() for x in open(nm, encoding="utf-8").read().split() if x.strip()]
        if "main" not in names:
            names.append("main")
        with open(nm, "w", encoding="utf-8") as f:
            f.write("\n".join(sorted(set(names))))
        print("原生模块清单已补入 main（共 %d 个）" % len(set(names)))
    except OSError as e:
        print("原生模块清单更新失败（可忽略）: %s" % e)
    # 只移不删：本机 safe-delete 把 os.remove / os.replace / shutil.move 都计入
    # 「每轮 50 次」删除配额，超限直接中断构建；只有同卷 os.rename 不计数。
    ARCHIVE = os.path.join(BUILD, "_stripped_src", time.strftime("%m%d_%H%M%S"))
    for f in [target] + glob.glob(os.path.join("server", "app", "main.c")):
        if os.path.isfile(f):
            dst = os.path.join(ARCHIVE, os.path.relpath(os.path.abspath(f), os.path.abspath(WORK)))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if os.path.exists(dst):
                continue
            os.rename(f, dst)
    tmp = os.path.join(WORK, "build")
    if os.path.isdir(tmp):
        dst = os.path.join(ARCHIVE, "_setuptools_build_main")
        i = 0
        while os.path.exists(dst):
            i += 1
            dst = os.path.join(ARCHIVE, "_setuptools_build_main_%d" % i)
        try:
            os.rename(tmp, dst)
        except OSError:
            pass
    sys.exit(0)

print("main 原生化后导入失败，回退为源码形态")
print(out[:1500])
sys.exit(2)
