#!/usr/bin/env bash
#
# 律师本地工作台 · 本地引擎一键准备脚本（OCR + 语音转写，全部离线运行）—— macOS / Linux 版
# 与 tools/prepare_engines.ps1 等价。
#
# 用法：
#   bash tools/prepare_engines.sh [base|small|medium]
#   默认 small（中文转写质量与体积平衡）
#
# 说明：
#   - OCR 中文模型随 RapidOCR wheel 内置，无需额外下载。
#   - 语音模型下载到 resources/models，走 hf-mirror 镜像，避免直连 HuggingFace 失败。
#   - macOS 若想用 Tesseract：brew install tesseract tesseract-lang
#     装好后程序会自动从 PATH 找到（server/app/media.py 的 _bundled_tesseract 兜底逻辑）。
set -euo pipefail

MODEL_SIZE="${1:-small}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8
# 国内 HuggingFace 镜像，避免模型下载失败
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
# hf-mirror 不转发 xet 通道，强制普通 HTTP 下载
export HF_HUB_DISABLE_XET=1

PY="${LW_PYTHON:-python3}"

echo "[1/3] 安装本地 OCR / 语音引擎（RapidOCR + faster-whisper，版本均已实测锁定）..."
"$PY" -m pip install -r requirements.txt

echo "[2/3] 校验 OCR 引擎（中文模型随 RapidOCR wheel 内置，无需额外下载）..."
"$PY" -c "from rapidocr_onnxruntime import RapidOCR; RapidOCR(); print('OCR_ENGINE_OK')"

echo "[3/3] 下载本地语音模型 faster-whisper-$MODEL_SIZE 到 resources/models ..."
"$PY" tools/download_models.py "$MODEL_SIZE"

echo ""
echo "全部完成。OCR 中文识别模型已内置；语音模型位于 resources/models。"
echo "若希望改用 Tesseract（macOS）：brew install tesseract tesseract-lang"
echo "  安装后程序会自动从 PATH 识别；也可将其整体复制到 resources/tesseract/（含 tessdata/chi_sim.traineddata）。"
