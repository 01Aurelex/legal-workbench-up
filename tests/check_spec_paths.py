# -*- coding: utf-8 -*-
"""回归测试：PyInstaller 的 .spec 必须能在「没有 __file__」的命名空间里执行。

背景（真实事故）：
  PyInstaller 是用 exec(code, spec_namespace) 执行 .spec 的，注入的是
  SPECPATH / SPEC / DISTPATH / WORKPATH 等变量，**命名空间里没有 __file__**。
  一旦 .spec 里写了 `os.path.abspath(__file__)`，构建会在
      NameError: name '__file__' is not defined
  处直接失败，而且只在真正跑 PyInstaller 那一刻暴露——`compileall` 语法检查
  和发布形态冒烟自测都发现不了它（本仓库就因此让 macOS 构建连续失败两轮）。

本测试用桩件复刻 PyInstaller 的执行环境（**不依赖真的装 PyInstaller**），
把每个 build/*.spec 完整执行一遍，要求：
  1) 不抛异常（尤其是 NameError）；
  2) 解析出的构建目录就是 spec 所在目录（路径本地化没有跑偏）。

用法：python tests/check_spec_paths.py
"""
from __future__ import annotations

import os
import pathlib
import sys
import types

REPO = pathlib.Path(__file__).resolve().parents[1]
SPECS = sorted((REPO / "build").glob("*.spec"))


def _install_pyinstaller_stubs() -> None:
    """拦住 `from PyInstaller.utils.hooks import collect_all` 与构建类。

    这里直接覆盖 sys.modules，保证本机就算装了真 PyInstaller 也走桩件，
    从而做到「秒级、零依赖、与平台无关」。
    """
    pi = types.ModuleType("PyInstaller")
    pi.__path__ = []                                     # type: ignore[attr-defined]
    utils = types.ModuleType("PyInstaller.utils")
    utils.__path__ = []                                  # type: ignore[attr-defined]
    hooks = types.ModuleType("PyInstaller.utils.hooks")
    hooks.collect_all = lambda *a, **k: ([], [], [])     # type: ignore[attr-defined]
    hooks.collect_submodules = lambda *a, **k: []        # type: ignore[attr-defined]
    hooks.collect_data_files = lambda *a, **k: []        # type: ignore[attr-defined]
    hooks.collect_dynamic_libs = lambda *a, **k: []      # type: ignore[attr-defined]
    sys.modules["PyInstaller"] = pi
    sys.modules["PyInstaller.utils"] = utils
    sys.modules["PyInstaller.utils.hooks"] = hooks


class _Stub:
    """Analysis / PYZ / EXE / COLLECT / BUNDLE 的统一替身。"""

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        # Analysis(...) 的返回值要被 a.pure / a.scripts / a.binaries / a.datas 取用
        self.pure = []
        self.scripts = []
        self.binaries = []
        self.datas = []
        self.zipfiles = []
        self.dependencies = []
        self.name = kwargs.get("name") or "stub"


def check_spec(spec: pathlib.Path) -> list[str]:
    problems: list[str] = []
    src = spec.read_text(encoding="utf-8")

    ns: dict = {
        # PyInstaller 注入的变量（注意：故意不提供 __file__）
        "SPECPATH": str(spec.parent),
        "SPEC": str(spec),
        "SPECFILE": str(spec),
        "DISTPATH": str(REPO / "build" / "out"),
        "WORKPATH": str(REPO / "build" / "tmp"),
        "__name__": "__main__",
        "__builtins__": __builtins__,
        "Analysis": _Stub, "PYZ": _Stub, "EXE": _Stub,
        "COLLECT": _Stub, "BUNDLE": _Stub, "Tree": _Stub, "MERGE": _Stub,
    }
    _install_pyinstaller_stubs()

    try:
        exec(compile(src, str(spec), "exec"), ns)  # noqa: S102
    except NameError as e:
        problems.append(
            "%s 在「无 __file__」命名空间下执行失败：%s\n"
            "  -> .spec 由 PyInstaller 以 exec() 执行，命名空间里没有 __file__，"
            "请改用 SPECPATH 定位本目录" % (spec.name, e))
        return problems
    except Exception as e:  # noqa: BLE001
        problems.append("%s 执行失败：%s: %s" % (spec.name, type(e).__name__, e))
        return problems

    want = os.path.normcase(str(spec.parent))
    for key in ("BUILD", "_LW_BUILD"):
        got = ns.get(key)
        if got is None:
            continue
        if os.path.normcase(os.path.abspath(str(got))) != want:
            problems.append("%s 的 %s 解析为 %s，期望 %s"
                            % (spec.name, key, got, spec.parent))
    if "ROOT" in ns and not str(ns["ROOT"]).endswith("src"):
        problems.append("%s 的 ROOT 解析为 %s，期望 .../src" % (spec.name, ns["ROOT"]))
    return problems


def main() -> int:
    if not SPECS:
        print("未找到 build/*.spec，跳过")
        return 0

    all_problems: list[str] = []
    for spec in SPECS:
        problems = check_spec(spec)
        if problems:
            all_problems += problems
            print("FAIL %s" % spec.name)
            for p in problems:
                print("     " + p.replace("\n", "\n     "))
        else:
            print("OK   %s" % spec.name)

    if all_problems:
        print("\n::error::PyInstaller spec 执行回归测试未通过（%d 项）" % len(all_problems))
        return 1
    print("\n通过：%d 个 spec 均可在无 __file__ 的命名空间下正常执行" % len(SPECS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
