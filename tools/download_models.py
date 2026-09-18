# -*- coding: utf-8 -*-
"""一键下载本地语音模型到 resources/models（默认 faster-whisper small）。
国内网络自动走 hf-mirror.com 镜像；模型只下载一次，之后完全离线运行。"""
from __future__ import annotations
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "resources" / "models"
MODELS.mkdir(parents=True, exist_ok=True)

# 国内镜像（不影响已能直连 HuggingFace 的环境）
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
# hf-mirror 不转发 xet(cas-server) 通道，强制走普通 HTTP 下载，否则 model.bin 会 401
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

SIZE = sys.argv[1] if len(sys.argv) > 1 else "small"
REPO = f"Systran/faster-whisper-{SIZE}"
DEST = MODELS / f"whisper-{SIZE}"


def main() -> None:
    from huggingface_hub import snapshot_download
    print(f"[1/2] 下载 {REPO} -> {DEST}（镜像：{os.environ['HF_ENDPOINT']}）")
    path = snapshot_download(
        repo_id=REPO,
        local_dir=str(DEST),
        allow_patterns=["config.json", "model.bin", "tokenizer.json",
                        "vocabulary.*", "vocab.*", "merges.txt", "preprocessor_config.json"],
        max_workers=1,
    )
    print(f"[2/2] 完成：{path}")
    print("media.py 将优先加载该本地模型目录，语音转写全程离线。")


if __name__ == "__main__":
    main()
