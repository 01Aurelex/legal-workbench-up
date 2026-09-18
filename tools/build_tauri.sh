#!/usr/bin/env bash
#
# 一键构建 Tauri 桌面应用 —— macOS / Linux 版（与 tools/build_tauri.ps1 等价）
#
# macOS 产物：
#   src-tauri/target/release/bundle/macos/法岩律师本地工作台.app
#   src-tauri/target/release/bundle/dmg/法岩律师本地工作台_0.9.12_aarch64.dmg
#
# 前置：Rust（https://rustup.rs）、Node.js、且已跑过 tools/build_sidecar.sh
#
# 用法：bash tools/build_tauri.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

export PYTHONUTF8=1

# ---------------------------------------------------------------- 工具链
command -v node >/dev/null 2>&1 || {
    echo "!! 未检测到 Node.js（@tauri-apps/cli 需要）。macOS：brew install node" >&2
    exit 1
}
if ! command -v cargo >/dev/null 2>&1 && [ -f "$HOME/.cargo/env" ]; then
    # shellcheck disable=SC1091
    . "$HOME/.cargo/env"
fi
command -v cargo >/dev/null 2>&1 || {
    echo "!! 未检测到 cargo。请先安装 Rust：curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh" >&2
    exit 1
}

# ---------------------------------------------------------------- sidecar
SIDECAR="$ROOT/build/out/legal-workbench/legal-workbench"
if [ ! -f "$SIDECAR" ]; then
    echo "未找到 sidecar，先构建后端..."
    bash "$ROOT/tools/build_sidecar.sh"
else
    echo "沿用已有 sidecar：$SIDECAR"
    echo "（如需重建，请手动运行 tools/build_sidecar.sh）"
fi

# ---------------------------------------------------------------- 前端依赖
if [ ! -d node_modules ]; then
    echo "安装 @tauri-apps/cli ..."
    npm install
fi

# ---------------------------------------------------------------- 图标
if [ "$(uname -s)" = "Darwin" ]; then
    ICON="$ROOT/src-tauri/icons/icon.icns"
else
    ICON="$ROOT/src-tauri/icons/icon.ico"
fi
if [ ! -f "$ICON" ]; then
    echo "!! 缺少 $ICON。图标设计源在 build/icon/（icon.svg + icon_512.png），请先用 npx tauri icon 生成。" >&2
    exit 1
fi

# ---------------------------------------------------------------- 强制 build script 重跑
# tauri-build 的 rerun-if-changed 不监听 icons/ 与 resources 内容，改过图标或换过
# sidecar 后不 touch build.rs 会沿用缓存，导致「换了图但包没变」这种诡异现象。
# 详见 build/构建说明.md 第 3.1 节。
if [ -f "$ROOT/src-tauri/build.rs" ]; then
    touch "$ROOT/src-tauri/build.rs"
    echo "已 touch src-tauri/build.rs，强制重新生成资源。"
fi

# ---------------------------------------------------------------- 签名
# Apple Silicon 上未签名的可执行文件会被系统直接杀掉（Killed: 9），
# 因此这里默认做 ad-hoc 签名（identity 为 "-"）。要正式分发再换成
# Apple Developer 证书 + 公证，见 README 的 macOS 章节。
if [ "$(uname -s)" = "Darwin" ]; then
    export APPLE_SIGNING_IDENTITY="${APPLE_SIGNING_IDENTITY:--}"
    echo "macOS 签名身份：${APPLE_SIGNING_IDENTITY}"
fi

# ---------------------------------------------------------------- 打包
# 基础配置 tauri.conf.json 的 bundle.targets 是 ["nsis"]（Windows 专属），
# macOS 上必须由平台覆盖文件 tauri.macos.conf.json 顶成 ["app","dmg"]。
# 若该覆盖文件因路径/命名问题未被合并，就会退回去做 nsis 而直接报错，
# 所以这里再显式传一次 --bundles，双保险。调用方自己传了 --bundles 则以调用方为准。
BUNDLE_ARGS=()
if [ "$(uname -s)" = "Darwin" ]; then
    case " $* " in
        *" --bundles "*) ;;
        *) BUNDLE_ARGS=(--bundles app,dmg) ;;
    esac
fi

echo "开始 Tauri 构建（首次编译 Rust 依赖较久，可能 10-30 分钟）..."
npx tauri build "${BUNDLE_ARGS[@]}" "$@"

echo ""
echo "完成。产物位于 src-tauri/target/release/bundle/"
ls -1d src-tauri/target/release/bundle/*/ 2>/dev/null || true
