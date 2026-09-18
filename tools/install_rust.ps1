# 安装 Rust 工具链（Tauri 编译需要）。已安装则跳过。
$ErrorActionPreference = "Stop"
$cargo = Get-Command cargo -ErrorAction SilentlyContinue
if ($cargo) {
    Write-Host "已检测到 Rust：" -ForegroundColor Green
    cargo --version
    return
}
Write-Host "未检测到 Rust，下载 rustup-init.exe 并静默安装（stable-msvc）..." -ForegroundColor Cyan
$tmp = Join-Path $env:TEMP "rustup-init.exe"
Invoke-WebRequest -Uri "https://win.rustup.rs/x86_64" -OutFile $tmp
& $tmp -y --default-toolchain stable --default-host x86_64-pc-windows-msvc
$env:Path = "$env:USERPROFILE\.cargo\bin;$env:Path"
cargo --version
Write-Host "Rust 安装完成。若编译报错缺少 Microsoft C++ Build Tools，请安装 VS Build Tools（含 MSVC + Windows SDK）。" -ForegroundColor Yellow
