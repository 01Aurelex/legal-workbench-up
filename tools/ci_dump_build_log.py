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
MAX_ANN = 10          # 最多发几条注解（平台每个 check-run 允许 50 条）
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


def _probe_artifacts(build: str) -> str:
    """直接探查产物现场。

    为什么需要它：CI 步骤自己的 stdout（例如 build_sidecar.sh 的 [2/2] 校验）
    在 REST 上是读不到的，一旦校验步骤判失败，外面只能看到
    "Process completed with exit code 1"。这里在失败后于同一工作区里
    把 build/out 的真实内容列出来，远程就能知道到底产出了什么。
    """
    lines = []
    outdir = os.path.join(build, "out")

    def listing(path, limit=40):
        if not os.path.isdir(path):
            lines.append("  <不存在: %s>" % path)
            return
        try:
            entries = sorted(os.scandir(path), key=lambda e: e.name)
        except OSError as e:
            lines.append("  <无法列出 %s: %r>" % (path, e))
            return
        lines.append("  %s/（%d 项）" % (path, len(entries)))
        for e in entries[:limit]:
            try:
                if e.is_dir(follow_symlinks=False):
                    lines.append("    [目录] %s" % e.name)
                else:
                    st = e.stat()
                    lines.append("    %10d  %s%s" % (st.st_size, e.name,
                                                     "  [可执行]" if os.access(e.path, os.X_OK) else ""))
            except OSError as err:
                lines.append("    <?> %s (%r)" % (e.name, err))
        if len(entries) > limit:
            lines.append("    ...（其余 %d 项省略）" % (len(entries) - limit))

    lines.append("########## 产物现场 ##########")
    lines.append("build 目录 = %s" % os.path.abspath(build))
    listing(outdir, 20)
    listing(os.path.join(outdir, "legal-workbench"), 60)

    # PyInstaller 到底把可执行文件生成成了什么名字
    pyi = os.path.join(build, "_pyi_build.log")
    if os.path.isfile(pyi):
        want = re.compile(r"Building EXE|EXE-00|checking EXE|distpath|Building COLLECT|"
                          r"Appending PKG|Copying bootloader|Building PKG")
        hits = []
        with open(pyi, encoding="utf-8", errors="replace") as fh:
            for i, ln in enumerate(fh, 1):
                if want.search(ln):
                    hits.append("    %6d | %s" % (i, ln.rstrip()[:220]))
        lines.append("  _pyi_build.log 中与 EXE/COLLECT 相关的行（共 %d，末 10 行）：" % len(hits))
        lines.extend(hits[-10:] or ["    <无匹配>"])
    return "\n".join(lines)


def _plan(build):
    """返回 [(标题, 正文)]，按「最可能含报错」排序。"""
    steps = sorted(glob.glob(os.path.join(build, "_step_*.log")), key=_step_key)
    pyi = os.path.join(build, "_pyi_build.log")
    crash = pyi + ".crash"
    allog = os.path.join(build, "_build_all.log")
    shlog = os.path.join(build, "_sidecar_sh.log")

    plan = []

    def add(title, path, n):
        if os.path.isfile(path):
            t = _read(path)
            if t.strip():
                plan.append((title + " | " + os.path.basename(path),
                             _tail(_fold_long_lines(t), n)))

    # ① 入口脚本自己的日志 + 产物现场：校验步骤失败时，这里才有答案
    add("① 入口脚本日志", shlog, 2500)
    plan.append(("①b 产物现场", _probe_artifacts(build)))

    # ② 失败步骤自己的日志（run_pyi 的步骤日志只是空壳，见下方降级）
    fail_step = steps[-1] if steps else None
    fail_txt = _read(fail_step) if fail_step else ""
    if len(fail_txt.strip()) > 260:
        add("② 失败步骤日志", fail_step, 2500)
    # ③ PyInstaller 原始日志
    add("③ PyInstaller 日志", pyi, 6000)
    # ④ faulthandler 崩溃现场
    add("④ 崩溃现场", crash, 2000)
    # ⑤ 失败的步骤日志（空壳也留一条，确认它确实没输出）
    if fail_step and len(fail_txt.strip()) <= 260:
        add("⑤ 失败步骤日志（几乎为空）", fail_step, 500)
    # ⑥ 总日志
    add("⑥ 总日志", allog, 4000)
    # ⑦ 其余步骤日志（倒序）
    for p in reversed(steps[:-1]):
        add("⑦ 前序步骤日志", p, 1000)
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
