# -*- coding: utf-8 -*-
"""把构建日志与环境信息转成 GitHub Actions 注解，便于远程诊断 macOS 构建失败。

为什么需要它：
  CI 上的失败日志只能由仓库管理员从网页查看（REST 的 /logs 接口需要 admin 权限），
  但 **check-run 的 annotations 接口对公开仓库是匿名的**。
  于是这里把日志尾部转成一条 `::error::` 注解发出去，任何能读 API 的人都能看到报错原文，
  不必让仓库主人手工复制日志。

用法（在 workflow 的 if: failure() 步骤里）：
    python tools/ci_dump_build_log.py [build 目录，默认 build]

设计要点：
  · 注解有长度上限，且报错总在日志**尾部** → 每条日志截取「头 800 + 尾 5000」字符；
  · 值里 % 必须最先转义成 %25，再转义换行，否则二次转义；
  · 同时把同样内容打到 stdout，人工在网页上看日志时也直接可见。
"""
from __future__ import annotations

import glob
import os
import sys

HEAD = 800
TAIL = 5000
MAX_TOTAL = 58000  # 留出余量，注解上限 64K


def _tail_excerpt(text: str) -> str:
    if len(text) <= HEAD + TAIL:
        return text
    return (text[:HEAD]
            + "\n...[中间省略 %d 字符]...\n" % (len(text) - HEAD - TAIL)
            + text[-TAIL:])


def _env_info() -> str:
    import platform
    import sysconfig

    lines = [
        "os            = %s %s" % (platform.system(), platform.release()),
        "machine       = %s" % platform.machine(),
        "python        = %s" % sys.version.replace("\n", " "),
        "sys.executable= %s" % sys.executable,
        "CC            = %s" % sysconfig.get_config_var("CC"),
        "CXX           = %s" % sysconfig.get_config_var("CXX"),
        "CFLAGS        = %s" % sysconfig.get_config_var("CFLAGS"),
        "platform tag  = %s" % sysconfig.get_platform(),
    ]
    for mod, label in (("Cython", "cython"), ("setuptools", "setuptools"),
                       ("PyInstaller", "pyinstaller")):
        try:
            m = __import__(mod)
            lines.append("%-13s = %s" % (label, getattr(m, "__version__", "?")))
        except Exception as e:  # noqa: BLE001
            lines.append("%-13s = <未安装: %s>" % (label, e))
    # clang / gcc 版本：macOS 上的编译失败几乎都出在这里
    import subprocess
    for cmd in (["cc", "--version"], ["clang", "--version"]):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
            first = (r.stdout or r.stderr or "").strip().splitlines()
            if first:
                lines.append("%-13s = %s" % (cmd[0], first[0]))
                break
        except Exception:  # noqa: BLE001
            pass
    return "\n".join(lines)


def main() -> int:
    build = sys.argv[1] if len(sys.argv) > 1 else "build"

    parts = ["########## 环境 ##########", _env_info()]

    pats = [os.path.join(build, "_build_all.log"),
            os.path.join(build, "_step_*.log"),
            os.path.join(build, "_pyi_build.log"),
            os.path.join(build, "_pyi_build.log.crash")]
    seen = set()
    found = []
    for pat in pats:
        for p in sorted(glob.glob(pat)):
            if p in seen:
                continue
            seen.add(p)
            found.append(p)

    if not found:
        parts.append("\n########## 未找到任何构建日志 ##########")
    for p in found:
        try:
            t = open(p, encoding="utf-8", errors="replace").read()
        except OSError as e:
            t = "<读取失败: %r>" % (e,)
        parts.append("\n########## %s ##########\n%s" % (p, _tail_excerpt(t)))

    msg = "\n".join(parts)
    # 人类可读版本
    print(msg, flush=True)
    # 注解版本（% 必须先转义）
    esc = msg.replace("%", "%25").replace("\r", "").replace("\n", "%0A")
    if len(esc) > MAX_TOTAL:
        esc = esc[:MAX_TOTAL] + "...[注解已截断]"
    print("::error::" + esc, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
