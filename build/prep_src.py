# -*- coding: utf-8 -*-
"""准备打包源树：
1) 从源码工程复制 server/，剔除授权体系（license.py 及其调用）；
2) 从 v0.9.12 发行版复制已修复的前端（去授权 / 提醒中心已知悉修复）；
3) 复制静态数据（法律法规库、文书模板）与图标；
4) 注入运行时防护（反调试 / 完整性校验 / 单实例）。
产物：build/src/
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
import re
import shutil
import sys
import time

# 路径均可通过环境变量覆盖，便于在 macOS / CI 上复用同一脚本
SRC = os.environ.get("LW_SRC", _LW_ROOT)
DIST = os.environ.get("LW_DIST", _LW_DIST)
BUILD = os.environ.get("LW_BUILD", _LW_BUILD)
WORK = os.path.join(BUILD, "src")

log = []


def step(msg: str) -> None:
    log.append(msg)
    print(msg, flush=True)


def rmtree(p: str) -> None:
    """清空目录：本机 safe-delete 策略会拦截批量删除（抛 SystemExit，连 BaseException
    都不一定能兜住），因此**完全不调用删除**，改为把旧目录改名成 <name>_old_<时间戳>，
    构建结束后人工清理即可。重命名不触发该策略。"""
    if not os.path.isdir(p):
        return
    stamp = time.strftime("%m%d_%H%M%S")
    dst = f"{p}_old_{stamp}"
    i = 0
    while os.path.exists(dst):
        i += 1
        dst = f"{p}_old_{stamp}_{i}"
    os.rename(p, dst)


def copytree(src: str, dst: str, ignore=None) -> None:
    os.makedirs(dst, exist_ok=True)
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", ".git", "node_modules")]
        rel = os.path.relpath(root, src)
        out = dst if rel == "." else os.path.join(dst, rel)
        os.makedirs(out, exist_ok=True)
        for f in files:
            if ignore and ignore(f):
                continue
            shutil.copy2(os.path.join(root, f), os.path.join(out, f))


# ---------------------------------------------------------------- 1. 清空
step("[1/6] 清空工作目录 " + WORK)
rmtree(WORK)
os.makedirs(WORK, exist_ok=True)

# ---------------------------------------------------------------- 2. server
step("[2/6] 复制后端 server/（剔除 license）")
copytree(os.path.join(SRC, "server"), os.path.join(WORK, "server"),
         ignore=lambda f: f in ("license.py",))

# ---------------------------------------------------------------- 3. 去授权
step("[3/6] 剔除后端授权体系")
mp = os.path.join(WORK, "server", "app", "main.py")
src_text = open(mp, encoding="utf-8").read()
orig = src_text

IMPORT_OLD = ("               media, mail, case_import, doctpl, intake, license as lic, llm_runtime)")
IMPORT_NEW = ("               media, mail, case_import, doctpl, intake, llm_runtime)")
if IMPORT_OLD in src_text:
    src_text = src_text.replace(IMPORT_OLD, IMPORT_NEW)
else:
    src_text = src_text.replace("license as lic, ", "")

GATE = '''@app.middleware("http")
async def license_gate(request: Request, call_next):
    """未激活仅开放案件管理：其余 API 一律 403 锁定（激活后全放行）。"""
    path = request.url.path
    if path.startswith("/api/") and path != "/api/bootstrap":
        if not lic.api_allowed(path, request.method):
            st = lic.license_status()
            return JSONResponse({"ok": False, "locked": True,
                                 "error": "软件尚未激活，免费版仅可使用案件管理，激活后解锁全部功能"},
                                status_code=403)
    return await call_next(request)

'''
if GATE in src_text:
    src_text = src_text.replace(GATE, "")
else:
    step("    ! 未找到 license_gate 原文，改用正则删除")
    src_text = re.sub(
        r'@app\.middleware\("http"\)\s*\nasync def license_gate.*?return await call_next\(request\)\n\n',
        "", src_text, flags=re.S)

src_text = src_text.replace(
    "return ok(token=get_or_create_token(), license=lic.license_status())",
    "return ok(token=get_or_create_token())")

# 删除 /api/license/* 路由段
src_text = re.sub(
    r'# =+ 授权激活（一机一码） =+\n(?:@app\.\w+\("/api/license/.*?\n(?:    .*\n|)*?\n)+',
    "", src_text)
if "/api/license/" in src_text:
    step("    ! 仍有 /api/license 残留，逐行剔除")
    lines = src_text.split("\n")
    out, skip = [], False
    for ln in lines:
        if "/api/license/" in ln:
            skip = True
            continue
        if skip:
            if ln.startswith("@app.") or (ln and not ln.startswith((" ", "\t", "@")) and not ln.rstrip().endswith(":")):
                skip = False
            else:
                continue
        out.append(ln)
    src_text = "\n".join(out)

assert "lic." not in src_text, "仍存在 lic. 调用"
assert "license_gate" not in src_text, "仍存在 license_gate"
open(mp, "w", encoding="utf-8").write(src_text)
step("    main.py: %d → %d 字节" % (len(orig), len(src_text)))

# ---------------------------------------------------------------- 4. frontend
step("[4/6] 复制已修复前端")
fe_src = os.path.join(SRC, "frontend")
if not os.path.isfile(os.path.join(fe_src, "index.html")):
    fe_src = os.path.join(DIST, "_internal", "frontend")
if not os.path.isdir(fe_src):
    raise SystemExit("找不到前端: " + fe_src)
copytree(fe_src, os.path.join(WORK, "frontend"))
# Tauri 外壳的启动加载页（WebviewUrl::App("loading.html")）
lg = os.path.join(SRC, "frontend_legacy_v0.9.11", "loading.html")
if os.path.isfile(lg):
    shutil.copy2(lg, os.path.join(WORK, "frontend", "loading.html"))
    step("    已补回 loading.html")

# ---------------------------------------------------------------- 5. 静态数据
step("[5/6] 复制静态数据与图标")
for sub in ("law_library", "templates"):
    s = os.path.join(SRC, "data", sub)
    if os.path.isdir(s):
        copytree(s, os.path.join(WORK, "data", sub))
ico = os.path.join(SRC, "build", "app.ico")
# 仓库版本里 SRC/build 与 BUILD 是同一个目录，直接照搬会变成"自己拷自己"（WinError 32）
if os.path.isfile(ico) and os.path.abspath(ico) != os.path.abspath(os.path.join(BUILD, "app.ico")):
    shutil.copy2(ico, os.path.join(BUILD, "app.ico"))
    step("    图标已就位")
elif os.path.isfile(os.path.join(BUILD, "app.ico")):
    step("    图标已在位")

# ---------------------------------------------------------------- 6. 注入防护
step("[6/6] 注入运行时防护")
guard_src = os.path.join(BUILD, "guard.py")
if not os.path.isfile(guard_src):
    raise SystemExit("缺少 guard.py")
shutil.copy2(guard_src, os.path.join(WORK, "server", "guard.py"))

fm = os.path.join(WORK, "server", "frozen_main.py")
t = open(fm, encoding="utf-8").read()
if "server.guard" not in t:
    t = t.replace("def main() -> int:\n    _ensure_utf8()\n",
                  "def main() -> int:\n    _ensure_utf8()\n"
                  "    import server.guard as guard\n"
                  "    guard.arm()\n")
    t = t.replace("""    cfg = load_config()
    host, port = cfg["host"], cfg["port"]""",
                  """    cfg = load_config()
    host, port = cfg["host"], cfg["port"]
    if not guard.single_instance(host, port):
        return 2
    if not guard.verify_integrity(getattr(sys, "_MEIPASS", "")):
        guard.alert("程序完整性校验失败，文件可能已被篡改。\\n请重新下载安装本软件。")
        return 3""")
    open(fm, "w", encoding="utf-8").write(t)
    step("    frozen_main.py 已注入")
else:
    step("    frozen_main.py 已注入（跳过）")

step("\n完成。源树: " + WORK)
print("\n".join(log))
