<#
  一键构建 Tauri 桌面安装包（NSIS）。

  前置：Rust + MSVC（可先跑 tools\install_rust.ps1）、Node.js、Python 依赖已安装。

  用法：powershell -ExecutionPolicy Bypass -File tools\build_tauri.ps1
  产物：src-tauri\target\release\bundle\nsis\
#>
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$env:PYTHONUTF8 = "1"

# ---------------------------------------------------------------- Rust
if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
    $cargoBin = Join-Path $env:USERPROFILE ".cargo\bin"
    if (Test-Path (Join-Path $cargoBin "cargo.exe")) {
        $env:Path = "$cargoBin;$env:Path"
    } else {
        Write-Host "未检测到 cargo，先执行 Rust 安装..." -ForegroundColor Yellow
        & powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "install_rust.ps1")
        $env:Path = "$cargoBin;$env:Path"
    }
}

# ---------------------------------------------------------------- sidecar
$sidecar = Join-Path $root "build\out\legal-workbench\legal-workbench.exe"
if (-not (Test-Path $sidecar)) {
    Write-Host "未找到 sidecar，先构建后端..." -ForegroundColor Yellow
    & powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "build_sidecar.ps1")
} else {
    Write-Host "沿用已有 sidecar：$sidecar" -ForegroundColor Cyan
    Write-Host "（如需重建，请手动运行 tools\build_sidecar.ps1）" -ForegroundColor DarkGray
}

# ---------------------------------------------------------------- 前端依赖
if (-not (Test-Path "node_modules")) {
    Write-Host "安装 @tauri-apps/cli ..." -ForegroundColor Cyan
    npm install
}

# ---------------------------------------------------------------- 图标
if (-not (Test-Path "src-tauri\icons\icon.ico")) {
    throw "缺少 src-tauri\icons\icon.ico。图标设计源在 build\icon\（icon.svg + icon_512.png），请先用 npx tauri icon 生成。"
}

# ---------------------------------------------------------------- 强制 build script 重跑
# tauri-build 的 rerun-if-changed 不监听 icons/ 与 resources 内容，改过图标或换过
# sidecar 后不 touch build.rs 会沿用缓存，导致「换了图但安装包没变」这种诡异现象。
# 详见 build\构建说明.md 第 3.1 节。
$bs = Join-Path $root "src-tauri\build.rs"
if (Test-Path $bs) {
    (Get-Item $bs).LastWriteTime = Get-Date
    Write-Host "已 touch src-tauri\build.rs，强制重新生成资源。" -ForegroundColor DarkGray
}

# ---------------------------------------------------------------- 打包
Write-Host "开始 Tauri 构建（首次编译 Rust 依赖较久，可能 5-15 分钟）..." -ForegroundColor Cyan
npx tauri build
if ($LASTEXITCODE -ne 0) { throw "Tauri 构建失败（退出码 $LASTEXITCODE）" }

Write-Host "完成。安装包位于 src-tauri\target\release\bundle\nsis\" -ForegroundColor Green
