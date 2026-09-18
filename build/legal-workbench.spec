# -*- mode: python ; coding: utf-8 -*-
"""法岩律师本地工作台 —— 加固打包规格（Windows / macOS 通用）

加固层次：
  1) 业务模块与入口全部经 Cython 3 编译为原生机器码（Windows .pyd / macOS .so），
     发行包内不存在这些模块的 Python 源码与 .pyc，反编译器无法还原逻辑；
     （注：PyInstaller 自 6.0 起移除了 PYZ 字节码加密，故改为全面原生化）
  2) 无控制台窗口 + 应用图标 + macOS Bundle 标识；
  3) 构建后由 make_manifest.py 生成 HMAC 完整性清单，启动时由已编译的 guard 校验；
  4) 反调试与单实例见 server/guard（同样为原生模块）。

构建：
  pyinstaller build/legal-workbench.spec --noconfirm --distpath build/out --workpath build/tmp
"""

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
import sys
from PyInstaller.utils.hooks import collect_all, collect_submodules

BUILD = os.path.abspath(SPECPATH)
ROOT = os.path.join(BUILD, "src")
ICON = os.path.join(BUILD, "app.ico")
IS_MAC = sys.platform == "darwin"
# Tauri 外壳内置后端：exe 必须叫 legal-workbench.exe（见 src-tauri/src/lib.rs）
if os.environ.get("LW_SIDECAR") == "1":
    APP_NAME = os.environ.get("LW_EXE_NAME") or "legal-workbench"
else:
    APP_NAME = os.environ.get("LW_EXE_NAME") or "法岩律师本地工作台"

# ---------------- 资源 ----------------
datas = [
    (os.path.join(ROOT, "frontend"), "frontend"),
    (os.path.join(ROOT, "data", "law_library"), os.path.join("data", "law_library")),
    (os.path.join(ROOT, "data", "templates"), os.path.join("data", "templates")),
]
binaries = []
# 关键：业务模块已编译为原生扩展，PyInstaller 无法静态分析其中的 import，
# 必须显式声明（否则运行时报 ModuleNotFoundError: sqlite3 之类）
NATIVE_HIDDEN = [
    # —— 被 Cython 模块使用的标准库 ——
    'base64', 'binascii', 'collections', 'contextlib', 'copy', 'csv', 'ctypes',
    'datetime', 'email', 'fnmatch', 'functools', 'glob', 'gzip', 'hashlib',
    'hmac', 'html', 'http', 'imaplib', 'io', 'itertools', 'json', 'logging',
    'math', 'mimetypes', 'os', 'pathlib', 'platform', 'random', 're', 'secrets',
    'shutil', 'smtplib', 'socket', 'sqlite3', 'ssl', 'stat', 'string',
    'subprocess', 'sys', 'tarfile', 'tempfile', 'threading', 'time', 'traceback',
    'typing', 'unicodedata', 'urllib', 'uuid', 'webbrowser', 'winreg', 'xml',
    'zipfile', 'zoneinfo',
    # email 子模块（发票邮件收发）
    'email.header', 'email.message', 'email.mime.audio', 'email.mime.base',
    'email.mime.image', 'email.mime.multipart', 'email.mime.text',
    'email.parser', 'email.policy', 'email.utils',
    'urllib.error', 'urllib.parse', 'urllib.request',
    'xml.dom.minidom', 'xml.etree.ElementTree',
    # Web 框架整体收编：原生化后无法靠静态分析发现其被引用的子模块
    'fastapi', 'fastapi.staticfiles', 'fastapi.responses', 'fastapi.routing',
    'fastapi.middleware', 'fastapi.middleware.cors', 'fastapi.exceptions',
    'starlette', 'starlette.staticfiles', 'starlette.responses',
    'starlette.middleware', 'starlette.middleware.errors',
    'starlette.middleware.cors', 'starlette.routing', 'starlette.background',
    'starlette.datastructures', 'starlette.requests', 'starlette.exceptions',
    'starlette.templating', 'starlette.applications', 'starlette.concurrency',
    'multipart', 'anyio', 'anyio._backends._asyncio', 'pydantic',
    # —— 第三方 ——
    'PIL', 'cryptography', 'docx', 'numpy', 'pypdf', 'watchdog', 'yaml', 'requests',
]
hiddenimports = [
    "uvicorn.lifespan.on",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.h11_impl",
    # 说明：uvicorn.protocols.websockets.auto 会被下面的 collect_submodules("uvicorn") 收进来，
    # 这是**有意保留**的——auto.py 自身用 try/except 兜底，只要 websockets/wsproto 两个包被
    # excludes 彻底排除，它就只会走 except 分支把 AutoWebSocketsProtocol 置为 None，不会崩。
    # 运行期我们已用 ws="none" 直接跳过该模块（见 server/frozen_main.py），双保险。
    "pkg_resources",
    "setuptools",
    # 原生化后 pkgutil 可能无法枚举扩展模块，显式列出本包全部子模块
    "server",
    "server.guard",
] + ["server.app." + m for m in (
    "ai_hub", "archive", "bitable", "case_import", "casetypes", "config", "db",
    "docgen", "doctpl", "intake", "integrations_feishu", "integrations_wechat",
    "invoice", "lawlib", "llm", "llm_runtime", "mail", "main", "media", "revenue",
    "scheduler", "security", "stats", "vault", "watcher", "workflow")] + NATIVE_HIDDEN

# 仅收集真正需要的第三方包（OCR / 语音 / 本地大模型等重型依赖为可选功能，
# 全部在函数内延迟导入，排除后可显著减小体积且不影响现有功能）
for pkg in ("docx", "pypdf", "openpyxl", "PIL", "watchdog", "cryptography"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass
hiddenimports += collect_submodules("server")
# 整体收编框架子模块（这些包本身未被编译，可被正常枚举）
for _pkg in ("fastapi", "starlette", "anyio", "pydantic", "requests", "uvicorn",
             "multipart", "email", "urllib", "xml", "http", "sqlite3"):
    try:
        hiddenimports += collect_submodules(_pkg)
    except Exception:
        pass

a = Analysis(
    [os.path.join(ROOT, "server", "frozen_main.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "matplotlib", "tkinter", "pytest", "paddleocr", "paddle",
        # 可选 AI / OCR / 语音引擎（v0.9.12 起界面已下线，均为延迟导入）
        "rapidocr_onnxruntime", "onnxruntime", "faster_whisper", "ctranslate2",
        "av", "cv2", "tokenizers", "huggingface_hub", "torch", "scipy",
        "IPython", "notebook", "pandas",
        # WebSocket 协议实现：本应用无任何 WS 端点，uvicorn 已用 ws="none" 关闭。
        # 若被“半收集”（只落盘 websockets/speedups*.pyd 而没有 __init__.py），
        # import websockets 会得到 namespace package，uvicorn 的 auto 模块随即抛
        # ImportError: cannot import name '__version__'，导致后端无法启动。
        "websockets", "wsproto",
        "websockets.speedups", "websockets.legacy", "websockets.sync",
        "websockets.asyncio", "websockets.extensions",
        "wsproto.utilities", "wsproto.frame_protocol", "wsproto.connection",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=os.path.join(BUILD, "entitlements.plist") if IS_MAC else None,
    icon=ICON if os.path.exists(ICON) else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)

if IS_MAC:
    app = BUNDLE(
        coll,
        name=APP_NAME + ".app",
        icon=ICON if os.path.exists(ICON) else None,
        bundle_identifier="cn.fayan.workbench",
        version="0.9.12",
        info_plist={
            "NSHighResolutionCapable": True,
            "NSRequiresAquaSystemAppearance": False,
            "CFBundleShortVersionString": "0.9.12",
            "CFBundleDisplayName": "法岩律师本地工作台",
            "LSMinimumSystemVersion": "11.0",
            "NSMicrophoneUsageDescription": "接案笔录语音转文字需要使用麦克风",
        },
    )
