# -*- coding: utf-8 -*-
"""构建完成后生成完整性清单 integrity.json（HMAC-SHA256 签名）并写入 _internal。

用法：python build/make_manifest.py <目标 _internal 目录>
清单缺失时守卫放行；清单存在但校验不过则拒绝启动。
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

import glob
import hashlib
import hmac
import json
import os
import sys

BUILD = os.environ.get("LW_BUILD", _LW_BUILD)


def load_key() -> bytes:
    sys.path.insert(0, BUILD)
    try:
        from guard import _key  # type: ignore
        return _key()
    except Exception:
        pass
    # 与 guard.py 完全一致的派生逻辑（兜底）
    import hashlib as _h
    a = _h.sha512(b"FaYan\x00LegalWorkbench" + b"integrity\x00guard\x00v1").digest()
    b = _h.sha256(bytes(i ^ 0x5A for i in a) + b"FaYan\x00LegalWorkbench").digest()
    c = _h.sha384(b + b"integrity\x00guard\x00v1" + a[::-1]).digest()
    return _h.sha256(a + b + c).digest()


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: python make_manifest.py <_internal 目录>")
        return 1
    base = os.path.abspath(sys.argv[1])
    if not os.path.isdir(base):
        print("目录不存在: " + base)
        return 1

    names = []
    nm = os.path.join(BUILD, "native_modules.txt")
    if os.path.isfile(nm):
        names = [x.strip() for x in open(nm, encoding="utf-8").read().split() if x.strip()]

    files = {}
    total = 0
    for n in names:
        pats = [os.path.join(base, "**", n + ".*.pyd"),
                os.path.join(base, "**", n + ".*.so"),
                os.path.join(base, "**", n + ".pyd"),
                os.path.join(base, "**", n + ".so")]
        for pat in pats:
            for p in glob.glob(pat, recursive=True):
                rel = os.path.relpath(p, base).replace("\\", "/")
                if rel not in files:
                    sz = os.path.getsize(p)
                    total += sz
                    files[rel] = sha256_file(p)
    # 附带 Python 运行时主库，防止整体替换解释器
    for extra in ("base_library.zip",):
        p = os.path.join(base, extra)
        if os.path.isfile(p):
            files[extra] = sha256_file(p)
            total += os.path.getsize(p)

    payload = json.dumps(files, sort_keys=True, separators=(",", ":")).encode("utf-8")
    sig = hmac.new(load_key(), payload, hashlib.sha256).hexdigest()
    out = os.path.join(base, "integrity.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"files": files, "sig": sig}, f, ensure_ascii=False, indent=1)
    print("已生成 %s：%d 个文件，%.1f MB" % (out, len(files), total / 1048576.0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
