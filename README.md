# 法岩律师本地工作台 · FaYan Legal Workbench

> **源码可见，但非开源软件。** 本仓库以 source-available 方式公开，版权归作者所有，
> 未经书面许可不得商用、修改或再分发。请先阅读 [`LICENSE`](LICENSE)。

面向执业律师的**本地优先（local-first）**桌面工作台：案件流程引擎、档案库、关系图谱、
模板文书库、要素式文书、接案笔录、创收与发票管理、提醒中心。

**全部业务数据、文档只保存在程序目录的 `data/` 下，默认不向任何公网上传。**

---

## 一、技术架构

```
┌─────────────────────────────────────────────────────────────┐
│  Tauri v2 桌面外壳（Rust + WebView2，NSIS 安装包）           │
│  · 单实例运行  · 窗口关闭即结束全部后台进程（无残留）        │
│  · 一次性本机令牌经环境变量注入，不落盘                      │
│         │ spawn（CREATE_NO_WINDOW）                          │
│         ▼                                                    │
│  Python 后端 sidecar（PyInstaller onedir + Cython 原生扩展） │
│  · FastAPI + Uvicorn，仅绑定 127.0.0.1:8765                  │
│  · Host 白名单防 DNS-rebind  · 随机令牌鉴权                  │
│         │                                                    │
│         ▼                                                    │
│  前端：原生 JS + Vue 3（ESM，无构建步骤），随外壳打包        │
└─────────────────────────────────────────────────────────────┘
```

- **后端**：Python 3.13，FastAPI。业务模块经 Cython 编译为原生扩展（`.pyd`），发行包内
  不存在可反编译的字节码，并由 `guard.py` 做完整性校验与单实例保护。
- **前端**：零构建的原生 JS + Vue 3 ESM，无 npm 打包步骤，离线无外部依赖。
- **打包**：PyInstaller `onedir` 产出 sidecar → Tauri `resources` 映射到安装目录
  `resources/sidecar/` → NSIS 生成安装包。

---

## 二、本仓库包含什么 / 不包含什么

| | 内容 |
|---|---|
| ✅ **包含** | `server/` 后端源码、`frontend/` 前端源码、`src-tauri/` Tauri 外壳工程、`build/` 构建管线、`tools/` 辅助脚本、`tests/` 自测、`data/law_library/` 法律库、`data/templates/` 234 份文书模板 |
| ❌ **不包含** | **激活签发后台（含 Ed25519 私钥，已整体排除）**、本地语音模型（约 460 MB）、内置大模型（约 2 GB）、PyInstaller/`target/` 等构建产物、任何运行时数据与密钥 |

模型与发行版产物一律由脚本按需生成，见 [第四节](#四从源码运行)。

---

## 三、目录结构

```
legal-workbench/
├─ server/                     # FastAPI 后端
│  ├─ launch.py                # 源码方式入口（python -m server.launch）
│  ├─ frozen_main.py           # PyInstaller 冻结入口
│  └─ app/                     # 业务模块
│     ├─ main.py               # 路由与中间件（最大单文件）
│     ├─ vault.py  archive.py  # 档案库 / 双链笔记
│     ├─ workflow.py           # 案件流程引擎（法定期限倒排）
│     ├─ doctpl.py docgen.py   # 模板文书库 / 要素式文书 / Word 生成
│     ├─ intake.py media.py    # 接案笔录（录音 + 离线转写）
│     ├─ bitable.py            # 类飞书多维表格总表
│     ├─ lawlib.py             # 本地法律库检索
│     ├─ revenue.py invoice.py # 创收 / 发票
│     ├─ scheduler.py          # 期限提醒与待外发队列
│     ├─ integrations_*.py     # 飞书 / 微信公众号（出方向，无需服务器）
│     ├─ security.py           # 鉴权、Host 白名单、密钥加密
│     └─ license.py            # 激活验签（**仅含 Ed25519 公钥**）
├─ frontend/                   # 原生 JS + Vue 3 ESM（无构建步骤）
│  ├─ index.html  loading.html
│  ├─ js/{app,core,ui,charts}.js  js/views/*.js
│  ├─ css/{app,fx,theme}.css
│  └─ vendor/vue.esm-browser.prod.js
├─ frontend_legacy_v0.9.11/    # 上一版前端留存（loading.html 供 Tauri 启动页使用）
├─ data/
│  ├─ law_library/             # 9 个文件、约 1850 个可检索条文块
│  ├─ templates/               # 234 份文书模板（起诉状答辩状 226 + 诉讼保全 8）
│  └─ vault/                   # 运行时数据（不入库，程序自动创建）
├─ resources/                  # 模型与引擎（不入库，脚本下载）；见 resources/README.md
├─ src-tauri/                  # Tauri v2 外壳工程
│  ├─ src/lib.rs               # 拉起 sidecar、令牌注入、单实例
│  ├─ tauri.conf.json          # 版本、NSIS 配置、resources 映射
│  └─ icons/
├─ build/                      # 构建管线（见 build/构建说明.md）
│  ├─ build_all.py             # 一键编排
│  ├─ prep_src.py              # 备源树（去授权 / 同步前端 / 注入守卫）
│  ├─ cythonize_app.py         # 业务模块 → 原生扩展
│  ├─ build_main_native.py     # 单独处理含 FastAPI 注解的 main.py
│  ├─ run_pyi.py               # PyInstaller 打包
│  ├─ make_manifest.py         # HMAC 完整性清单
│  ├─ guard.py                 # 反调试 / 完整性 / 单实例
│  └─ legal-workbench.spec     # PyInstaller 规格
├─ tools/                      # 模型下载、引擎准备、构建包装脚本
├─ tests/                      # smoke_test.py 等自测
└─ .github/workflows/          # CI：源码级校验（不产出未签名安装包）
```

---

## 四、从源码运行

### 4.1 环境要求

| 组件 | 版本 | 说明 |
|---|---|---|
| Python | **3.13**（构建机实测） | 3.10+ 亦可，但依赖版本分档不同，见 `requirements.txt` 注释 |
| Node.js | 22.x | 仅 Tauri 打包需要 |
| Rust | ≥ 1.77 | 仅 Tauri 打包需要 |
| MSVC | VS 2022（含 C++ 生成工具） | Cython 编译 `.pyd` 需要 |
| Windows SDK | 10 | 同上 |
| VC++ 可再发行组件 | 2015-2022 x64 **14.40+** | Whisper / ONNX Runtime 运行时需要 |

### 4.2 直接以源码启动（开发用）

```bat
python -m pip install -r requirements.txt
set PYTHONUTF8=1
python -m server.launch
```

或双击 `启动工作台.bat`。启动后仅监听 `127.0.0.1:8765`，数据写入本目录 `data/`。

### 4.3 准备本地引擎（可选）

```powershell
# OCR（RapidOCR，中文模型随 wheel 内置）+ 语音模型（faster-whisper small，约 460 MB）
powershell -ExecutionPolicy Bypass -File tools\prepare_engines.ps1

# 只下载语音模型（国内走 hf-mirror 镜像）
python tools\download_models.py small
```

未下载语音模型时，接案笔录的转写功能会给出明确提示，不影响其他模块。

### 4.4 构建 Windows 安装包

```powershell
# 1) 后端 sidecar（Cython + PyInstaller），产物在 build/out/legal-workbench/
powershell -ExecutionPolicy Bypass -File tools\build_sidecar.ps1

# 2) Tauri 外壳 + NSIS 安装包
powershell -ExecutionPolicy Bypass -File tools\build_tauri.ps1
# 安装包输出：src-tauri\target\release\bundle\nsis\
```

> **注意**：改动 `src-tauri/icons/` 或 `build/out/` 内容后，必须先 `touch src-tauri\build.rs`
> （或删除 `src-tauri\target` 下的对应缓存）再打包，否则新的资源不会被打进安装包。

构建细节、常见坑与排查方式见 [`build/构建说明.md`](build/构建说明.md)。

---

## 五、数据与隐私

| 项 | 位置 | 说明 |
|---|---|---|
| 业务数据 | `data/vault/`（客户 / 案件 / 材料 / 文书 / 笔记） | 正文落盘为 Markdown / Word，SQLite 仅作索引 |
| 数据库 | `data/workbench.sqlite3` | 删库可重建，不丢正文 |
| 密钥材料 | `data/.secret.key`、`data/.access_token` | 本机生成；集成密钥经 Fernet 加密后落盘 |
| 网络访问 | 默认无 | 仅绑定回环地址；飞书 / 微信 / 邮件等集成**默认关闭**，未配置时零外发 |

- 服务仅监听 `127.0.0.1`，并带随机令牌校验与 Host 白名单（伪造来源返回 403）。
- 备份：直接复制整个 `data/` 目录即可；删除程序目录即完成卸载，不写注册表。

---

## 六、第三方组件与许可

本软件依赖大量优秀的开源项目（FastAPI / Starlette / Uvicorn / Pydantic / python-docx /
cryptography / Pillow / watchdog / pypdf / openpyxl / requests / RapidOCR / faster-whisper /
CTranslate2 / ONNX Runtime / Vue.js 等），它们分别适用各自的开源许可证，不适用本仓库
`LICENSE` 的限制。完整依赖清单见 [`requirements.txt`](requirements.txt) 与
[`package.json`](package.json)。

`data/law_library/` 收录的法律文本、`data/templates/` 中源自最高人民法院示范文本的部分，
依《中华人民共和国著作权法》第五条不适用著作权保护。详见 [`LICENSE`](LICENSE) 第二条。

---

## 七、已知边界（诚实说明）

1. **授权校验非本仓库内容**：签发后台（含 Ed25519 私钥）已整体排除。`server/app/license.py`
   仅含**公钥**，可离线验签，但无法自行签发激活码。`build/prep_src.py` 会在打包时移除授权
   门禁，因此自行构建出的版本不包含试用限制。
2. **Windows 优先**：Cython 编译、NSIS 打包链路在 Windows 上验证通过；构建脚本保留了
   macOS 分支，但未做完整验证。
3. **版本号存在漂移**：`src-tauri/tauri.conf.json` 为 `0.9.12`，而 `Cargo.toml` /
   `package.json` 为 `1.0.0`。发布前需统一。
4. **模板与法律库需要人工维护**：法律库为静态文本，不会自动更新；修订后需重新走
   「导入向导」重建索引。
5. **自测**：服务启动后执行 `set PYTHONUTF8=1 && python tests/smoke_test.py`。

---

## 八、许可证

**保留所有权利（All Rights Reserved）。** 详见 [`LICENSE`](LICENSE)。

- 允许：为学习、研究、评估之目的阅读源码。
- 禁止：商业使用、修改后再分发、去除权利声明、镜像转载。
- 如需商业使用或二次分发，请联系作者取得书面许可。
