# =====================================================================
# 律师本地工作台 · 本地引擎一键准备脚本（OCR + 语音转写，全部离线运行）
# 用法：在项目根目录右键“用 PowerShell 运行”，或：
#   powershell -ExecutionPolicy Bypass -File tools\prepare_engines.ps1
# 可选参数：-ModelSize base|small|medium （默认 small，中文转写质量与体积平衡）
# =====================================================================
param([string]$ModelSize = "small")

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$env:PYTHONUTF8 = "1"
# 国内 HuggingFace 镜像，避免模型下载失败
$env:HF_ENDPOINT = "https://hf-mirror.com"
# hf-mirror 不转发 xet 通道，强制普通 HTTP 下载
$env:HF_HUB_DISABLE_XET = "1"

Write-Host "[1/3] 安装本地 OCR / 语音引擎（RapidOCR + faster-whisper，版本均已实测锁定）..." -ForegroundColor Cyan
python -m pip install -r requirements.txt

Write-Host "[2/3] 校验 OCR 引擎（中文模型随 RapidOCR wheel 内置，无需额外下载）..." -ForegroundColor Cyan
python -c "from rapidocr_onnxruntime import RapidOCR; RapidOCR(); print('OCR_ENGINE_OK')"

Write-Host "[3/3] 下载本地语音模型 faster-whisper-$ModelSize 到 resources\models ..." -ForegroundColor Cyan
python tools\download_models.py $ModelSize

Write-Host ""
Write-Host "全部完成。OCR 中文识别模型已内置；语音模型位于 resources\models。" -ForegroundColor Green
Write-Host "若仍希望使用 Tesseract：下载 https://github.com/UB-Mannheim/tesseract/wiki 安装时"
Write-Host "勾选 Chinese(Simplified)，再把安装目录整体复制到 resources\tesseract（含 tessdata\chi_sim.traineddata），程序会自动识别。"
