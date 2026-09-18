# -*- coding: utf-8 -*-
"""回归测试：`server/app/config.py` 的平台路径决策。

为什么值得单独测：这段逻辑决定「数据写到哪里」，改错了会在 macOS 上
把用户数据塞进 `.app` bundle（签名失效 / 覆盖安装丢数据），
或在 Windows 上把绿色便携的 `data/` 挪走（老用户找不到数据）。
而这两种情况在开发机上都不会自然暴露，所以用模拟冻结态把它钉死。

做法：config.py 只依赖标准库、无相对导入，把它 exec 进独立命名空间，
配合打桩 sys.frozen / sys.platform / sys.executable 与 Path.home 即可。
`Path.home` 会被指到临时目录，**不会**碰真实家目录。

用法：python tests/check_config_paths.py      （退出码 0 通过，1 失败）
"""
from __future__ import annotations

import os
import pathlib
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[1]
SRC = REPO / "server" / "app" / "config.py"
CODE = SRC.read_text(encoding="utf-8")

_TMP = pathlib.Path(tempfile.mkdtemp(prefix="lw_cfg_"))
_FAKE_HOME = _TMP / "home"
_FAKE_HOME.mkdir(parents=True, exist_ok=True)

lines: list[str] = []
fails: list[str] = []


def run(*, frozen: bool, platform: str, executable: str,
        data_override: str | None = None) -> dict:
    """在指定平台/冻结态下执行 config.py，返回其解析出的路径。"""
    g: dict = {"__name__": "cfg_under_test", "__file__": str(SRC)}

    had_frozen = hasattr(sys, "frozen")
    old_frozen = getattr(sys, "frozen", None)
    old_platform = sys.platform
    old_exe = sys.executable
    old_home = pathlib.Path.home
    old_env = os.environ.get("LW_DATA_DIR")

    pathlib.Path.home = classmethod(lambda cls: _FAKE_HOME)  # 隔离家目录
    try:
        if frozen:
            sys.frozen = True
            sys._MEIPASS = str(pathlib.Path(executable).parent)
        elif had_frozen:
            del sys.frozen
        sys.platform = platform
        sys.executable = executable
        if data_override:
            os.environ["LW_DATA_DIR"] = data_override
        else:
            os.environ.pop("LW_DATA_DIR", None)
        exec(compile(CODE, str(SRC), "exec"), g)
    finally:
        pathlib.Path.home = old_home
        sys.platform = old_platform
        sys.executable = old_exe
        if had_frozen:
            sys.frozen = old_frozen
        if old_env is None:
            os.environ.pop("LW_DATA_DIR", None)
        else:
            os.environ["LW_DATA_DIR"] = old_env

    return {k: g[k] for k in ("BASE_DIR", "DATA_DIR", "RESOURCES_DIR", "FROZEN")}


def check(label: str, got, want) -> None:
    if str(got) == str(want):
        lines.append("  OK   %-26s = %s" % (label, got))
    else:
        lines.append("  FAIL %-26s = %s" % (label, got))
        lines.append("       期望 = %s" % (want,))
        fails.append(label)


def main() -> int:
    # 1) 开发态：沿用仓库目录
    lines.append("=== 开发态（未冻结）===")
    r = run(frozen=False, platform="win32",
            executable=str(REPO / "python.exe"))
    check("dev BASE_DIR", r["BASE_DIR"], REPO)
    check("dev DATA_DIR", r["DATA_DIR"], REPO / "data")
    check("dev RESOURCES_DIR", r["RESOURCES_DIR"], REPO / "resources")

    # 2) 冻结态 Windows：必须仍是 exe 同级（老行为回归）
    lines.append("")
    lines.append("=== 冻结态 win32（回归：exe 同级 data/ 不变）===")
    win_dir = _TMP / "install" / "resources" / "sidecar"
    win_dir.mkdir(parents=True, exist_ok=True)
    win_exe = win_dir / "legal-workbench.exe"
    win_exe.write_bytes(b"MZ")
    r = run(frozen=True, platform="win32", executable=str(win_exe))
    check("win BASE_DIR", r["BASE_DIR"], win_dir)
    check("win DATA_DIR", r["DATA_DIR"], win_dir / "data")
    check("win RESOURCES_DIR", r["RESOURCES_DIR"], win_dir / "resources")

    # 3) 冻结态 macOS：数据外置，引擎留包内
    lines.append("")
    lines.append("=== 冻结态 darwin（数据外置，不进 .app）===")
    mac_exe = _TMP / "App.app" / "Contents" / "Resources" / "sidecar" / "legal-workbench"
    mac_exe.parent.mkdir(parents=True, exist_ok=True)
    mac_exe.write_bytes(b"\x7fELF")
    want_base = _FAKE_HOME / "Library" / "Application Support" / "法岩律师本地工作台"
    r = run(frozen=True, platform="darwin", executable=str(mac_exe))
    check("mac BASE_DIR", r["BASE_DIR"], want_base)
    check("mac DATA_DIR", r["DATA_DIR"], want_base / "data")
    check("mac RESOURCES_DIR", r["RESOURCES_DIR"], mac_exe.parent / "resources")
    if ".app" in str(r["DATA_DIR"]):
        lines.append("  FAIL 数据目录仍落在 .app bundle 内")
        fails.append("mac:data-inside-bundle")
    else:
        lines.append("  OK   数据目录已移出 .app bundle")

    # 4) LW_DATA_DIR 覆盖
    lines.append("")
    lines.append("=== LW_DATA_DIR 覆盖 ===")
    ovr = _TMP / "custom-data"
    r = run(frozen=True, platform="darwin", executable=str(mac_exe),
            data_override=str(ovr))
    check("override BASE_DIR", r["BASE_DIR"], ovr)
    check("override DATA_DIR", r["DATA_DIR"], ovr / "data")

    lines.append("")
    lines.append("全部通过" if not fails else "失败 %d 项: %s" % (len(fails), fails))
    print("\n".join(lines))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
