#!/usr/bin/env bash
#
# 构建 Tauri sidecar（内置 Python 后端）—— macOS / Linux 版
# 与 tools/build_sidecar.ps1 等价，共用同一条流水线。
#
# 实际流水线（顺序不可乱，详见 build/构建说明.md）：
#   prep_src → cythonize_app → finalize_native → build_main_native → PyInstaller → make_manifest
#
# 产物：build/out/legal-workbench/legal-workbench
#   （macOS / Linux 的可执行文件没有 .exe 后缀；src-tauri/src/lib.rs 按平台取名）
# 该目录正是 src-tauri/tauri.conf.json 中 bundle.resources 的映射源
#   （../build/out/legal-workbench → 应用内的 Resources/sidecar/），无需再手工同步。
#
# 前置：
#   - Python 3.13（建议用专属虚拟环境）
#   - Xcode Command Line Tools（macOS，提供 clang，Cython 编译原生模块要用）
#       xcode-select --install
#   - pip install -r requirements.txt cython pyinstaller
#
# 用法：bash tools/build_sidecar.sh
#   可用 LW_PYTHON 指定解释器（默认 python3）。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

PY="${LW_PYTHON:-python3}"

echo "[1/2] 构建 sidecar（Cython 原生化 + PyInstaller，首次或全量重编约 5-15 分钟）..."
"$PY" -X utf8 build/build_all.py --sidecar

echo "[2/2] 校验产物..."
OUT="$ROOT/build/out/legal-workbench"
EXE="$OUT/legal-workbench"

if [ ! -f "$EXE" ]; then
    echo "!! 未找到 $EXE —— 构建可能静默失败，请查看 build/_build_all.log 与 build/_pyi_build.log" >&2
    exit 1
fi

if [ ! -x "$EXE" ]; then
    chmod +x "$EXE"
    echo "已补上可执行权限：$EXE"
fi

if [ ! -f "$OUT/_internal/integrity.json" ]; then
    echo "! 缺少 _internal/integrity.json（完整性清单），发行包启动时会跳过校验"
fi

SIZE="$(du -sm "$OUT" | awk '{print $1}')"
echo "sidecar 就绪：$EXE（约 ${SIZE} MB）"
echo "可直接运行 tools/build_tauri.sh 打包 .app / .dmg。"
