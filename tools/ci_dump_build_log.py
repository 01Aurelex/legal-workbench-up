# -*- coding: utf-8 -*-
"""把构建日志与环境信息发布出去，便于远程诊断 macOS 构建失败。

为什么需要它：
  CI 的原始日志只能由仓库管理员从网页查看（REST 的 /logs 接口需要 admin 权限），
  但 **check-run 的 annotations 对公开仓库是匿名可读的**，于是把日志转成注解发出去。

踩过的坑（本脚本据此设计）：
  1. 单条 GitHub 工作流命令（::error::）的消息在约 3.7KB 处被硬截断，
     且「原文很长时恰好切在报错那一行之前」——因此不能只发一条大注解，
     改为**多条小注解**（每条 ≤3.3KB，最多 6 条），大幅提高拿到报错的概率。
  2. 作业摘要（$GITHUB_STEP_SUMMARY）虽然能在网页看到，但**不会出现在
     check-run 的 output 里**（实测 output.summary 为空），所以它只能作为
     人工看网页时的补充，不能作为远程诊断通道。
  3. 编译器命令行动辄上千字符，会把真正的报错挤出窗口 → 超长行单独折叠。
  4. run_pyi.py 把 stdout 重定向进了 _pyi_build.log，它自己的步骤日志几乎是空的
     → 不能只看「失败的步骤日志」，否则会拿到一份空注解。

用法（在 workflow 的 if: failure() 步骤里）：
    python tools/ci_dump_build_log.py [build 目录，默认 build]
"""
from __future__ import annotations

import glob
import os
import re
import sys

CHUNK = 3300          # 单条注解正文上限（平台约 3.7KB 处截断）
MAX_ANN = 6           # 最多发几条注解
LONG_LINE = 500       # 超过此长度的行视为编译器命令行噪音，折叠之
SUMMARY_BUDGET = 900_000


def _tail(text: str, n: int) -> str:
    if len(text) <= n:
        return text
    return "...[前 %d 字符省略]...\n" % (len(text) - n) + text[-n:]


def _fold_long_lines(text: str) -> str:
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
    import subprocess
    for cmd in (["cc", "--version"], ["clang", "--version"], ["sw_vers"]):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
            txt = (r.stdout or r.stderr or "").strip().splitlines()
            if txt:
                lines.append("%-13s = %s" % (cmd[0], " / ".join(txt[:2])))
                break
        except Exception:  # noqa: BLE001
            pass
    return "\n".join(lines)


def _read(p):
    try:
        return open(p, encoding="utf-8", errors="replace").read()
    except OSError as e:
        return "<读取失败: %r>" % (e,)


def _step_key(p):
    m = re.search(r"_step_(\d+)_", os.path.basename(p))
    return int(m.group(1)) if m else -1


def _plan(build):
    """返回 [(标题, 正文)]，按「最可能含报错」排序。"""
    steps = sorted(glob.glob(os.path.join(build, "_step_*.log")), key=_step_key)
    pyi = os.path.join(build, "_pyi_build.log")
    crash = pyi + ".crash"
    allog = os.path.join(build, "_build_all.log")

    plan = []

    def add(title, path, n):
        if os.path.isfile(path):
            t = _read(path)
            if t.strip():
                plan.append((title + " | " + os.path.basename(path),
                             _tail(_fold_long_lines(t), n)))

    # 1) 失败步骤自己的日志（除非它只是 run_pyi 的空壳，见下方判断）
    fail_step = steps[-1] if steps else None
    fail_txt = _read(fail_step) if fail_step else ""
    if len(fail_txt.strip()) > 260:
        add("① 失败步骤日志", fail_step, 3000)
    # 2) PyInstaller 原始日志：报错一般就在末尾
    add("② PyInstaller 日志", pyi, 7000)
    # 3) faulthandler 崩溃现场（若 PyInstaller 是段错误，这里才是关键）
    add("③ 崩溃现场", crash, 2500)
    # 4) 失败的步骤日志（即使是空壳，也留一条以便确认确实没输出）
    if fail_step and len(fail_txt.strip()) <= 260:
        add("④ 失败步骤日志（几乎为空）", fail_step, 600)
    # 5) 总日志
    add("⑤ 总日志", allog, 5000)
    # 6) 之前各步骤日志（倒序，越晚越相关）
    for p in reversed(steps[:-1]):
        add("⑥ 前序步骤日志", p, 1200)
    return plan


def main() -> int:
    build = sys.argv[1] if len(sys.argv) > 1 else "build"
    env = _env_info()
    plan = _plan(build)

    # ---------- 1) 作业摘要：完整内容，供人在网页上看 ----------
    parts = ["## macOS 构建诊断\n", "### 环境\n```\n%s\n```\n" % env]
    if not plan:
        parts.append("\n**未找到任何构建日志**\n")
    for title, body in plan:
        parts.append("\n### %s\n```\n%s\n```\n" % (title, body.rstrip()))
    summary = "\n".join(parts)[:SUMMARY_BUDGET]
    sum_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if sum_path:
        try:
            with open(sum_path, "a", encoding="utf-8") as f:
                f.write(summary)
        except OSError as e:
            print("写作业摘要失败: %r" % (e,), flush=True)

    # ---------- 2) stdout 也打一份，人在网页看日志时直接可见 ----------
    print("########## 环境 ##########", flush=True)
    print(env, flush=True)
    for title, body in plan:
        print("\n########## %s ##########" % title, flush=True)
        print(body.rstrip(), flush=True)

    # ---------- 3) 注解：切成多条，每条都在平台的截断线以内 ----------
    chunks = []
    cur = ""
    for title, body in plan:
        piece = "\n\n===== %s =====\n%s" % (title, body)
        if len(cur) + len(piece) <= CHUNK:
            cur += piece
            continue
        if cur:
            chunks.append(cur)
        # 单块正文本身超限时按行切
        while len(piece) > CHUNK:
            cut = piece.rfind("\n", 0, CHUNK)
            if cut <= 0:
                cut = CHUNK
            chunks.append(piece[:cut])
            piece = piece[cut:]
        cur = piece
    if cur:
        chunks.append(cur)
    # 环境压成一行，接到第一条注解开头（不单独占一条，免得浪费额度）
    key_env = subprocess_free_env_line()
    if chunks:
        chunks[0] = "环境: %s%s" % (key_env, chunks[0])
    else:
        chunks = ["环境: %s\n未找到任何构建日志（build=%s）" % (key_env, build)]

    for i, ck in enumerate(chunks[:MAX_ANN], 1):
        esc = ck.replace("%", "%25").replace("\r", "").replace("\n", "%0A")
        print("::error::[诊断 %d/%d]%s" % (i, min(len(chunks), MAX_ANN), esc), flush=True)
    if len(chunks) > MAX_ANN:
        print("::warning::诊断内容超过 %d 条注解上限，剩余内容仅见作业摘要"
              % MAX_ANN, flush=True)
    print("\n[诊断] 共 %d 条注解（上限 %d），作业摘要已写入: %s"
          % (len(chunks), MAX_ANN, bool(sum_path)), flush=True)
    return 0


def subprocess_free_env_line() -> str:
    """压成一行，放在第一条注解里，便于一眼看出平台/版本差异。"""
    import platform
    import sysconfig
    bits = ["%s %s" % (platform.system(), platform.release()),
            platform.machine(),
            "py%s" % platform.python_version(),
            "tag=%s" % sysconfig.get_platform()]
    for mod in ("Cython", "setuptools", "PyInstaller"):
        try:
            m = __import__(mod)
            bits.append("%s=%s" % (mod, getattr(m, "__version__", "?")))
        except Exception:  # noqa: BLE001
            bits.append("%s=?" % mod)
    return " | ".join(bits)


if __name__ == "__main__":
    raise SystemExit(main())
