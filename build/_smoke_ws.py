# -*- coding: utf-8 -*-
"""冒烟测试：启动 sidecar 后端，验证 8765 端口 HTTP 可达、无 websockets 崩溃。

用法：
  python build/_smoke_ws.py [exe路径] [端口] [--inject-broken-ws]

--inject-broken-ws：负面回归测试 —— 人为在 _internal 下塞入残缺的
  websockets 包（只有 speedups.pyd、无 __init__.py），复现历史崩溃场景，
  修复到位时（uvicorn ws="none" 根本不 import websockets）后端仍须正常启动。
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

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

argv = [a for a in sys.argv[1:] if not a.startswith("--")]
EXE = (argv[0] if len(argv) > 0
       else os.path.join(_LW_BUILD_OUT, "legal-workbench", "legal-workbench.exe"))
PORT = int(argv[1]) if len(argv) > 1 else 8765
INJECT = "--inject-broken-ws" in sys.argv
sdir = os.path.dirname(os.path.abspath(EXE))

# 后端监听端口来自 exe 同级 data/config.json（默认 8765）；探测端口必须以它为准
_cfgp = os.path.join(sdir, "data", "config.json")
if os.path.isfile(_cfgp):
    try:
        _cfg = json.load(open(_cfgp, encoding="utf-8"))
        if isinstance(_cfg.get("port"), int):
            PORT = _cfg["port"]
    except Exception:
        pass

rep = []
rep.append("EXE          : %s" % EXE)
rep.append("EXE exists   : %s" % os.path.isfile(EXE))
rep.append("探测端口      : %d" % PORT)
rep.append("模式          : %s" % ("负面回归（注入残缺 websockets）" if INJECT else "常规"))
internal = os.path.join(sdir, "_internal")
if os.path.isdir(internal):
    residue = [n for n in os.listdir(internal)
               if n.startswith("websockets") or n.startswith("wsproto")]
    rep.append("_internal WS残留: %s" % (residue if residue else "无（正确）"))
else:
    rep.append("_internal     : 目录不存在！%s" % internal)

errlog = os.path.join(sdir, "startup_error.log")
if os.path.isfile(errlog):
    # 清空上一轮崩溃记录（用 rename 归档，避免触发 safe-delete 配额）
    os.rename(errlog, errlog + "." + time.strftime("%m%d_%H%M%S") + ".old")

injected: list[str] = []
if INJECT:
    # 复现历史故障：只放 C 扩展、不放 __init__.py —— Python 会把它当 namespace package
    wsdir = os.path.join(internal, "websockets")
    if not os.path.isdir(wsdir):
        os.makedirs(wsdir)
    dummy = os.path.join(wsdir, "speedups.cp313-win_amd64.pyd")
    with open(dummy, "wb") as f:
        f.write(b"MZ" + b"\x00" * 510)
    injected.append(dummy)
    rep.append("已注入残缺包  : %s" % dummy)
    # 用 PathFinder 精确模拟冻结解释器（sys.path 仅 _internal）能看到的 websockets
    import importlib.machinery as _m
    sp = _m.PathFinder.find_spec("websockets", [internal], None)
    if sp is None:
        rep.append("注入后 find_spec('websockets'): None（场景未构造成功）")
    else:
        rep.append("注入后 origin : %r" % (sp.origin,))
        rep.append("注入后 submodule_search_locations: %r" % (list(sp.submodule_search_locations or []),))
        rep.append("loader        : %r" % (sp.loader,))
        rep.append("-> 构成 namespace package（无 __init__.py），"
                   "与历史崩溃场景一致" if not sp.origin else "-> 仍为常规包，场景不一致")

env = dict(os.environ)
env["LW_NO_BROWSER"] = "1"
env["LW_AUTO_TOKEN"] = "wstest"
env["PYTHONUTF8"] = "1"

p = subprocess.Popen([EXE], cwd=sdir, env=env,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
rep.append("PID          : %d" % p.pid)

base = "http://127.0.0.1:%d" % PORT
# 必须显式绕过环境里的 http_proxy：否则 urllib 会把回环请求发给代理，拿到 502 假失败
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
urllib.request.install_opener(_opener)
ok_root = ok_boot = False
last = ""
t0 = time.time()
while time.time() - t0 < 45:
    if p.poll() is not None:
        rep.append("进程已退出，returncode=%s（%.1fs）" % (p.returncode, time.time() - t0))
        break
    try:
        with _opener.open(base + "/", timeout=3) as r:
            if r.status == 200:
                ok_root = True
        with _opener.open(base + "/api/bootstrap?token=wstest", timeout=5) as r:
            body = r.read().decode("utf-8", "replace")
            if r.status == 200 and ("ok" in body[:200] or "token" in body[:200]):
                ok_boot = True
                last = body[:300]
        if ok_root and ok_boot:
            break
    except urllib.error.HTTPError as e:
        last = "HTTP %s" % e.code
    except Exception as e:
        last = "%s: %s" % (type(e).__name__, e)
    time.sleep(1.0)

rep.append("GET /            : %s" % ("200 OK" if ok_root else "FAIL(%s)" % last))
rep.append("GET /api/bootstrap: %s" % ("200 OK" if ok_boot else "FAIL"))
if last:
    rep.append("响应片段      : %s" % last.replace("\n", " ")[:300])
rep.append("耗时          : %.1fs" % (time.time() - t0))

try:
    p.terminate()
    p.wait(timeout=10)
except Exception:
    try:
        p.kill()
    except Exception:
        pass
rep.append("进程已停止    : %s" % (p.poll() is not None))

if injected:
    d = os.path.dirname(injected[0])
    try:
        os.rename(d, d + ".__smoketest")
        rep.append("已移除注入包  : %s" % d)
    except OSError as e:
        rep.append("注入包移除失败: %s" % e)

if os.path.isfile(errlog):
    txt = open(errlog, encoding="utf-8", errors="replace").read()
    rep.append("!! 发现 startup_error.log：")
    rep.append(txt[:2000])
else:
    rep.append("startup_error.log: 无（正常）")

verdict = "PASS" if (ok_root and ok_boot) else "FAIL"
rep.append("VERDICT      : %s" % verdict)
out = "\n".join(rep)
print(out)
open(os.path.join(_LW_BUILD, "_smoke_ws.txt"), "w", encoding="utf-8").write(out + "\n")
sys.exit(0 if verdict == "PASS" else 1)
