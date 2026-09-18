# resources/ —— 本地引擎与模型（不入版本库）

本目录下的模型与引擎文件**体积巨大（合计约 2.5 GB）**，且均可由官方渠道重新获取，
因此不纳入 Git 仓库（见根目录 `.gitignore` 的 `resources/*` 规则，仅保留本说明文件）。

自己构建/运行时，按需用脚本准备好即可：

## 1. 语音转写模型（接案笔录功能）

```powershell
# 下载 faster-whisper small 到 resources/models/whisper-small/（约 460 MB）
python tools\download_models.py small
# 可选：base / medium
python tools\download_models.py medium
```

脚本默认走 `hf-mirror.com` 镜像，并关闭 xet 通道（`HF_HUB_DISABLE_XET=1`），
否则 `model.bin` 会返回 401。模型只下载一次，之后语音转写全程离线。

未下载时，`server/app/media.py` 会返回明确提示，不影响其他模块。

## 2. OCR 引擎（图片文字识别）

无需额外下载 —— RapidOCR 的中文识别模型随 PyPI wheel 内置，`pip install -r requirements.txt`
即可。运行时依赖 VC++ 2015-2022 x64 可再发行组件（14.40 及以上）。

自检：

```powershell
python -c "from rapidocr_onnxruntime import RapidOCR; RapidOCR(); print('OCR_ENGINE_OK')"
```

## 3. 一键准备

```powershell
powershell -ExecutionPolicy Bypass -File tools\prepare_engines.ps1
```

---

## 预期目录形态

```
resources/
├─ README.md                      ← 本文件（唯一入库项）
└─ models/
   └─ whisper-small/
      ├─ config.json
      ├─ model.bin
      ├─ tokenizer.json
      ├─ vocabulary.json
      └─ ...
```

## 关于内置本地大模型

历史发行版曾在 `resources/llm/` 内置 llama.cpp 运行时与 Qwen2.5-3B 模型（约 2 GB）。
该目录同样不入库；如需重新引入，请自行评估模型许可证（Qwen2.5 采用 Apache-2.0）
并注意发行包体积。
