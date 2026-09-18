# -*- coding: utf-8 -*-
"""把构建日志与环境信息发布出去，便于远程诊断 macOS 构建失败。

为什么需要它：
  1. CI 的原始日志只能由仓库管理员从网页查看（REST 的 /logs 接口需要 admin 权限），
     但 **check-run 的 annotations 与作业摘要（job summary）对公开仓库是匿名可读的**。
  2. 注解（annotation）有很强的长度限制——实测单个 check-run 的注解文本合计约 4KB 就会
     被截断，踩过一次「内容正好切在报错那一行之前」的坑；
     而作业摘要上限约 1MB，且会出现在 check-run 的 output 里。
  故本脚本双通道发布：
     · 作业摘要（首选）：完整环境信息 + 各日志全文/长尾部；
     · 注解（兜底）：**只**放「失败那一步」的尾部，短小到绝不会被截断。

用法（在 workflow 的 if: failure() 步骤里）：
    python tools/ci_dump_build_log.py [build 目录，默认 build]

设计要点：
  · 失败步骤一定是最靠后的 _step_N_*.log，所以挑「序号最大」的那份；
  · 注解里 % 必须最先转义成 %25，再转义换行，否则二次转义；
  · 同时把内容打到 stdout，人工在网页看日志时也直接可见。
"""
from __future__ import annotations

import glob
import os
import re
import sys

# 注解：单个 check-run 的注解文本实测在 ~3.7KB 处被平台截断，这里留足余量。
ANN_TAIL = 3200
ANN_BUDGET = 3400
# 摘要：上限约 1MB，取 900KB 留余量。
SUMMARY_BUDGET = 900_000
# 超过这个长度的行视为「编译器命令行」噪音：一条 clang 命令能占上千字符，
# 会把真实的报错挤出注解窗口，因此单独折叠。
LONG_LINE = 500


def _tail(text: str, n: int) -> str:
    if len(text) <= n:
        return text
    return "...[前 %d 字符省略]...\n" % (len(text) - n) + text[-n:]


def _fold_long_lines(text: str) -> str:
    """把超长命令行折叠掉，让报错行在有限的注解额度里露出来。"""
    out = []
    for ln in text.splitlines():
        if len(ln) > LONG_LINE:
            out.append("<长命令行，已折叠 %d 字符> %s … %s"
                       % (len(ln), ln[:160], ln[-120:]))
        else:
            out.append(ln)
    return "\n".join(out)


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
        "ARFLAGS       = %s" % sysconfig.get_config_var("ARFLAGS"),
        "LDSHARED      = %s" % sysconfig.get_config_var("LDSHARED"),
        "MACOSX_DEPLOYMENT_TARGET = %s" % os.environ.get("MACOSX_DEPLOYMENT_TARGET"),
        "ARCHFLAGS     = %s" % os.environ.get("ARCHFLAGS"),
        "platform tag  = %s" % sysconfig.get_platform(),
    ]
    for mod, label in (("Cython", "cython"), ("setuptools", "setuptools"),
                       ("PyInstaller", "pyinstaller"), ("numpy", "numpy")):
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


def _collect(build: str):
    """按重要性排序返回 [(路径, 内容)]。失败步骤（序号最大的 _step_*）排最前。"""
    pats = [os.path.join(build, "_step_*.log"),
            os.path.join(build, "_build_all.log"),
            os.path.join(build, "_pyi_build.log"),
            os.path.join(build, "_pyi_build.log.crash")]

    def step_key(p):
        m = re.search(r"_step_(\d+)_", os.path.basename(p))
        return int(m.group(1)) if m else -1

    step_logs = sorted(glob.glob(pats[0]), key=step_key)
    ordered = []
    if step_logs:
        ordered.append(step_logs[-1])          # 失败的那一步：最重要
        ordered.extend(reversed(step_logs[:-1]))  # 其余步骤：倒序（越晚越相关）
    for pat in pats[1:]:
        ordered.extend(sorted(glob.glob(pat)))

    out = []
    seen = set()
    for p in ordered:
        if p in seen:
            continue
        seen.add(p)
        try:
            t = open(p, encoding="utf-8", errors="replace").read()
        except OSError as e:
            t = "<读取失败: %r>" % (e,)
        out.append((p, t))
    return out


def main() -> int:
    build = sys.argv[1] if len(sys.argv) > 1 else "build"
    env = _env_info()
    logs = _collect(build)

    # ---------------- 1) 作业摘要：完整内容（公开可读，容量大） ----------------
    parts = ["## macOS 构建诊断\n", "### 环境\n```\n%s\n```\n" % env]
    if not logs:
        parts.append("\n**未找到任何构建日志**\n")
    for p, t in logs:
        keep = t if len(t) <= 20000 else _tail(t, 20000)
        parts.append("\n### `%s`（%d 字符，显示末尾部分）\n```\n%s\n```\n"
                     % (p, len(t), keep.rstrip()))
    summary = "\n".join(parts)
    if len(summary) > SUMMARY_BUDGET:
        summary = summary[:SUMMARY_BUDGET] + "\n...[摘要已截断]...\n"

    sum_path = os.environ.get("GITHUB_STEP_SUMMARY")
    summary_written = False
    if sum_path:
        try:
            with open(sum_path, "a", encoding="utf-8") as f:
                f.write(summary)
            summary_written = True
        except OSError as e:
            print("写作业摘要失败: %r" % (e,))

    # stdout 也打一份，人在网页看日志时直接可见
    print("########## 环境 ##########")
    print(env)
    for p, t in logs:
        print("\n########## %s ##########" % p)
        print(_tail(t, 20000).rstrip())

    # ---------------- 2) 注解：只放失败的这一步（绝不被 4KB 截断） ----------------
    head = ""
    if logs:
        p, t = logs[0]
        head = "失败步骤日志：%s\n" % p
        body = _tail(_fold_long_lines(t), ANN_TAIL)
    else:
        body = "未找到任何构建日志（build=%s）" % build
    msg = head + body
    if len(msg) > ANN_BUDGET:
        msg = msg[-ANN_BUDGET:]
    esc = msg.replace("%", "%25").replace("\r", "").replace("\n", "%0A")
    print("::error::" + esc, flush=True)
    print("\n[诊断] 作业摘要已写入: %s" % summary_written, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
