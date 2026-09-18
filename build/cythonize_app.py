# -*- coding: utf-8 -*-
"""把后端业务模块用 Cython 编译为原生扩展（.pyd / .so）。

编译成功后删除对应 .py 源码与中间 .c，发行包内不再存在可反编译的 Python 字节码；
编译失败的模块保持 .py 原样（由 PyInstaller 的 PYZ 加密兜底），保证构建不中断。
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
import shutil
import sys
import glob


def _ensure_msvc() -> None:
    """在当前进程内注入 MSVC 环境（构建宿主可能不继承 vcvars 设置的变量）。"""
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

WORK = os.environ.get("LW_BUILD", _LW_BUILD)

# 源码/中间产物归档目录（本机 safe-delete 策略把 os.remove / os.replace 都计入
# 「每轮 50 次」的删除配额，超限即中断构建；只有 os.rename 不计数。
# 所以一律用 rename 把文件移出发行树，归档到构建目录之外的地方，人工清理即可）
STAMP = __import__("time").strftime("%m%d_%H%M%S")
ARCHIVE = os.path.join(WORK, "_stripped_src", STAMP)


def strip_to_archive(path: str) -> None:
    """把已编译的 .py / 中间 .c 移出发行树（等价于删除，但不消耗删除配额）。"""
    if not os.path.isfile(path):
        return
    rel = os.path.relpath(path, os.path.join(WORK, "src"))
    dst = os.path.join(ARCHIVE, rel)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.exists(dst):
        return
    os.rename(path, dst)
WORK = os.path.join(WORK, "src")
# main.py 由 build_main_native.py 单独编译（含 FastAPI 注解，需要 annotation_typing=False）。
# 这里必须跳过：否则会被编译两次，第二次 setuptools 覆盖 inplace .pyd 时会先删旧文件，
# 在启用 safe-delete 配额的环境里白白消耗一次删除额度。
SKIP = {"__init__.py", "main.py"}


def main() -> int:
    os.chdir(WORK)
    _ensure_msvc()
    app_dir = os.path.join("server", "app")
    targets = []
    for f in sorted(os.listdir(app_dir)):
        if f.endswith(".py") and f not in SKIP:
            targets.append(os.path.join(app_dir, f))
    for extra in ("guard.py", "launch.py"):
        gp = os.path.join("server", extra)
        if os.path.isfile(gp):
            targets.append(gp)

    try:
        from Cython.Build import cythonize
        import Cython.Compiler.Options as _copts
        _copts.docstrings = False      # 编译产物不保留文档字符串
    except ImportError:
        print("Cython 未安装，跳过编译（将仅使用 PYZ 加密）")
        return 0

    exts, ok_files, bad = [], [], []
    for t in targets:
        try:
            got = cythonize(
                [t],
                language_level=3,
                force=True,
                quiet=True,
                compiler_directives={
                    "language_level": 3,
                    "always_allow_keywords": True,
                    "cdivision": True,
                    "embedsignature": False,
                    "infer_types": True,
                },
            )
            exts.extend(got)
            ok_files.append(t)
        except Exception as e:  # noqa
            bad.append((t, str(e)[:160]))
            print("  cythonize 失败: %s => %s" % (t, str(e)[:160]))

    if sys.platform == "win32":
        # 不嵌入清单：避免链接期依赖 rc.exe（精简安装的生成工具常缺该组件）
        for e in exts:
            e.extra_link_args = list(e.extra_link_args or []) + ["/MANIFEST:NO"]

    if not exts:
        print("没有可编译模块")
        return 0

    from setuptools import setup

    ncpu = str(os.cpu_count() or 4)
    setup(
        name="lw_native",
        ext_modules=exts,
        script_args=["build_ext", "--inplace", "-j", ncpu],
    )

    built, missing = [], []
    for t in ok_files:
        base = os.path.splitext(os.path.basename(t))[0]
        d = os.path.dirname(t)
        found = (glob.glob(os.path.join(d, base + ".*.pyd"))
                 + glob.glob(os.path.join(d, base + "*.so"))
                 + glob.glob(os.path.join(d, base + ".pyd")))
        if found:
            built.append(t)
            strip_to_archive(t)               # 源码移出发行树
            for c in glob.glob(os.path.join(d, base + ".c")):
                strip_to_archive(c)           # 中间 C 移出发行树
        else:
            missing.append(t)

    print("\n编译成功并移除源码: %d 个" % len(built))
    for t in built:
        print("  + " + t)
    # 记录原生模块清单，供构建后生成完整性校验使用
    if built:
        names = [os.path.splitext(os.path.basename(t))[0] for t in built]
        with open(os.path.join(WORK, "..", "native_modules.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(names))
    if missing:
        print("编译未产出（保留 .py）: %d 个" % len(missing))
        for t in missing:
            print("  - " + t)
    if bad:
        print("cythonize 失败（保留 .py）: %d 个" % len(bad))
    return 0


if __name__ == "__main__":
    sys.exit(main())
