# -*- coding: utf-8 -*-
"""源码模式冒烟：拉起 `python -m server.launch`，等端口就绪后跑 tests/smoke_test.py，最后收尾。

本地与 CI 共用。相比手动开两个终端，这里保证：
  · 显式绕过 http_proxy（否则探测回环地址会拿到 502 假失败）；
  · 结束后必定回收子进程，不留 8765 占用；
  · 子进程输出落盘到 build/_smoke_server.log，失败时可回溯。

用法：
  python tests/run_smoke.py                       # 默认 8765，跑全部自测
  python tests/run_smoke.py --port 8899           # 换端口
  python tests/run_smoke.py --skip-ocr            # CI：跳过 OCR 项（未装引擎时）
  python tests/run_smoke.py --root build/src      # 针对「去授权后的可发布源树」测试

说明：直接针对仓库根跑，会命中 server/app/main.py 里的授权门禁（未激活仅开放案件管理），
多数接口返回 403。CI 因此先执行 build/prep_src.py，再用 --root build/src 测试发布形态。
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _arg(name):
    """取 --xxx value 形式的参数值，不存在返回 None。"""
    if name not in sys.argv:
        return None
    i = sys.argv.index(name) + 1
    return sys.argv[i] if i < len(sys.argv) else None


PORT = int(_arg("--port") or 8765)

_root = _arg("--root")
if _root:
    ROOT = Path(_root) if Path(_root).is_absolute() else (REPO / _root)
    ROOT = ROOT.resolve()
else:
    ROOT = REPO

# 透传给 smoke_test.py 的开关（--port / --root 及其取值不转发）
SMOKE_ARGS = [a for a in sys.argv[1:] if a.startswith("--") and a not in ("--port", "--root")]

LOG = REPO / "build" / "_smoke_server.log"
LOG.parent.mkdir(parents=True, exist_ok=True)

env = dict(os.environ)
env["PYTHONUTF8"] = "1"
env["LW_NO_BROWSER"] = "1"          # 不要弹浏览器
env.pop("http_proxy", None)
env.pop("https_proxy", None)

logf = open(LOG, "w", encoding="utf-8", errors="replace")
proc = subprocess.Popen([sys.executable, "-X", "utf8", "-m", "server.launch"],
                        cwd=str(ROOT), env=env,
                        stdout=logf, stderr=subprocess.STDOUT)

# 必须显式绕过代理，否则回环请求会被发给 http_proxy 拿到 502
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
url = "http://127.0.0.1:%d/api/bootstrap" % PORT

ready = False
t0 = time.time()
while time.time() - t0 < 60:
    if proc.poll() is not None:
        print("[ERROR] 后端进程已退出，returncode=%s，日志见 %s" % (proc.returncode, LOG))
        break
    try:
        with opener.open(url, timeout=3) as r:
            if r.status == 200:
                ready = True
                break
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):        # 端口已在服务，只是鉴权/白名单生效
            ready = True
            break
    except Exception:
        pass
    time.sleep(1.0)

if not ready:
    print("[ERROR] 等待 127.0.0.1:%d 就绪超时（%.0fs）。" % (PORT, time.time() - t0))
    tail = ""
    try:
        tail = LOG.read_text(encoding="utf-8", errors="replace")[-3000:]
    except Exception:
        pass
    print("---- 后端输出尾部 ----\n" + tail)

code = 1
try:
    if ready:
        print("[OK] 后端已就绪，开始自测（%.1fs）" % (time.time() - t0))
        env["LW_SMOKE_ROOT"] = str(ROOT)      # 告诉 smoke_test.py 被测服务的数据根在哪
        code = subprocess.call([sys.executable, "-X", "utf8",
                                str(REPO / "tests" / "smoke_test.py")] + SMOKE_ARGS,
                               cwd=str(REPO), env=env)
finally:
    try:
        proc.terminate()
        proc.wait(timeout=15)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
    logf.close()

print("[smoke] 退出码 %d，后端日志：%s" % (code, LOG))
sys.exit(code)
