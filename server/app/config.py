# -*- coding: utf-8 -*-
"""全局路径与运行配置。

数据只落在本机本地目录，不写注册表、不向公网上传；具体位置见下方 BASE_DIR：
  · Windows 安装版 / 源码模式：程序目录下的 data/
  · macOS 安装版：~/Library/Application Support/法岩律师本地工作台/data/
两者都可用环境变量 LW_DATA_DIR 覆盖。
"""
from __future__ import annotations
import json
import os
import shutil
import sys
from pathlib import Path

# 冻结打包（PyInstaller/Tauri sidecar）时：
#   只读资源（前端、种子法律库）位于解包资源目录 _MEIPASS；
#   内置引擎（OCR / 语音 / 本地大模型）始终相对【可执行文件】所在目录的 resources/，
#   因为它们是随包分发的只读内容，不随数据目录走。
FROZEN = getattr(sys, "frozen", False)
if FROZEN:
    EXE_DIR = Path(sys.executable).resolve().parent
    RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", EXE_DIR))
else:
    EXE_DIR = Path(__file__).resolve().parents[2]           # legal-workbench/
    RESOURCE_DIR = EXE_DIR

RESOURCES_DIR = EXE_DIR / "resources"                   # 内置引擎（OCR/语音模型）目录

# 可写数据根目录 BASE_DIR：
#   Windows / 开发态 —— exe 同级（绿色便携，卸载即删净，与原行为一致）；
#   macOS 冻结态    —— ~/Library/Application Support/<产品名>
#     macOS 上 .app 对用户是「一个文件」，其内部的 Contents/Resources/sidecar/
#     可能只读（直接从只读的 .dmg 运行、或装在非管理员账户的 /Applications），
#     而且往已签名的 bundle 里写文件会破坏签名封条（应用可能直接打不开），
#     覆盖安装也会整体替换该目录、清掉用户数据。故按 Apple 规范外置到用户库目录。
#   LW_DATA_DIR 环境变量可强制指定（测试/多开用）。
_override = os.environ.get("LW_DATA_DIR", "").strip()
if _override:
    BASE_DIR = Path(_override).expanduser()
elif FROZEN and sys.platform == "darwin":
    BASE_DIR = Path.home() / "Library" / "Application Support" / "法岩律师本地工作台"
else:
    BASE_DIR = EXE_DIR

DATA_DIR = BASE_DIR / "data"
VAULT_DIR = DATA_DIR / "vault"                          # Obsidian 式 Markdown 档案库
LAWLIB_DIR = DATA_DIR / "law_library"                   # 本地法律库（RAG 唯一知识源）
TPL_DIR = DATA_DIR / "templates"                        # 文书模板库（起诉状/答辩状/保全）
DOCX_DIR = VAULT_DIR / "文书"                           # 生成的 Word 文书存放处
DB_PATH = DATA_DIR / "workbench.sqlite3"
CONFIG_PATH = DATA_DIR / "config.json"
TOKEN_PATH = DATA_DIR / ".access_token"
KEY_PATH = DATA_DIR / ".secret.key"
AUDIT_PATH = DATA_DIR / "audit.log"
EXPORT_DIR = DATA_DIR / "export"
FRONTEND_DIR = RESOURCE_DIR / "frontend"                # 只读前端（冻结时来自打包资源）
BUNDLED_LAWLIB = RESOURCE_DIR / "data" / "law_library"  # 随包种子法律库
BUNDLED_TPL = RESOURCE_DIR / "data" / "templates"       # 随包种子文书模板库

try:
    for _d in (DATA_DIR, VAULT_DIR, LAWLIB_DIR, TPL_DIR, DOCX_DIR, EXPORT_DIR,
               VAULT_DIR / "客户", VAULT_DIR / "案件", VAULT_DIR / "材料",
               VAULT_DIR / "文书", VAULT_DIR / "笔记"):
        _d.mkdir(parents=True, exist_ok=True)
except OSError as _e:
    # 数据目录不可写属于致命问题（数据库、档案库都无处安放），
    # 但必须给出可操作的提示，而不是抛一个只有 traceback 的异常。
    raise RuntimeError(
        "数据目录不可写：%s\n"
        "请确认该目录存在且当前用户有写权限；"
        "macOS 可设环境变量 LW_DATA_DIR 指向可写位置（如 ~/Documents/法岩工作台）。" % DATA_DIR
    ) from _e

# 首次运行（冻结包）：若本地法律库为空，把随包种子法律库复制到可写 data 目录
if FROZEN and BUNDLED_LAWLIB.exists() and not list(LAWLIB_DIR.glob("*.md")):
    for _f in BUNDLED_LAWLIB.glob("*"):
        if _f.is_file():
            shutil.copy2(_f, LAWLIB_DIR / _f.name)

# 首次运行（冻结包）：若本地模板库为空，把随包种子文书模板复制到可写 data 目录
if FROZEN and BUNDLED_TPL.exists() and not any(TPL_DIR.rglob("*.docx")):
    shutil.copytree(BUNDLED_TPL, TPL_DIR, dirs_exist_ok=True)

DEFAULT_CONFIG = {
    "host": "127.0.0.1",           # 仅绑定本机回环，不对局域网/公网暴露
    "port": 8765,
    "llm": {
        "provider": "bundled",     # 内置 llama.cpp（随包封入，开箱即用）；可改 ollama/openai
        "base_url": "http://127.0.0.1:8766/v1",
        "model": "qwen2.5-3b-instruct-q4_k_m",
        "temperature": 0.2,
        "strict_law_only": True    # AI 仅依据本地法律库作答
    },
    "feishu": {"enabled": False, "app_id": "", "app_secret": "", "folder_token": ""},
    # 飞书多维表格（一键同步档案总表/案件表/客户表/创收表/提醒表）
    "bitable": {"app_token": "", "table_ids": {}},
    # 发票邮箱自动收取
    "invoice": {"enabled": False, "imap_host": "imap.qq.com", "imap_port": 993,
                "imap_ssl": True, "username": "", "folder": "INBOX",
                "days": 30, "only_unseen": True, "keywords": "发票,invoice,增值税,电子发票",
                "auto_notify": True, "interval_minutes": 30},
    # 开放 AI 对话（默认内置 llama.cpp，可切 Ollama / OpenAI 兼容端点）
    "ai": {"provider": "bundled", "base_url": "http://127.0.0.1:8766/v1",
           "model": "qwen2.5-3b-instruct-q4_k_m", "temperature": 0.3, "max_context_messages": 12,
           "system_prompt": "", "strict_law_only": True, "timeout": 240},
    # 微信公众号：无需公网服务器的“纯出方向”提醒。
    # send_mode: kf=客服消息(48小时互动窗口内) / template=服务号模板消息 / subscribe=一次性订阅消息
    # sandbox=True 时使用微信公众平台测试号 AppID/Secret，便于零资质先行联调
    "wechat": {"enabled": False, "appid": "", "appsecret": "", "token": "",
               "open_kfid": "", "send_mode": "kf", "template_id": "",
               "default_openid": "", "sandbox": False},
    # 邮件提醒（日程到期通过 SMTP 发信）
    "mail": {"enabled": False, "smtp_host": "smtp.qq.com", "smtp_port": 465,
             "ssl": True, "username": "", "from_name": "法岩律师工作台", "to_addr": ""},
    "security": {"lock_after_minutes": 30, "audit": True},
    "lawlib": {"remind_after_days": 90},
    # 界面：首页招呼词（greeting 为空则显示默认「Hello，world」）
    "ui": {"greeting": ""},
}


def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            cfg = json.loads(json.dumps(DEFAULT_CONFIG))
            for k, v in saved.items():
                if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                    cfg[k].update(v)
                else:
                    cfg[k] = v
            return cfg
        except Exception:
            pass
    save_config(DEFAULT_CONFIG)
    return json.loads(json.dumps(DEFAULT_CONFIG))


def save_config(cfg: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(CONFIG_PATH, 0o600)
    except OSError:
        pass
