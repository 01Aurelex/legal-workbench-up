<#
  构建 Tauri sidecar（内置 Python 后端）。

  实际流水线（顺序不可乱，详见 build/构建说明.md）：
    prep_src → cythonize_app → finalize_native → build_main_native → PyInstaller → make_manifest

  产物：build\out\legal-workbench\legal-workbench.exe
  该目录正是 src-tauri\tauri.conf.json 中 bundle.resources 的映射源
  （../build/out/legal-workbench → 安装后的 resources\sidecar\），无需再手工同步。

  用法：powershell -ExecutionPolicy Bypass -File tools\build_sidecar.ps1
  可用 LW_PYTHON 指定解释器（默认 python）。
#>
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

$py = if ($env:LW_PYTHON) { $env:LW_PYTHON } else { "python" }

Write-Host "[1/2] 构建 sidecar（Cython 原生化 + PyInstaller，首次或全量重编约 3-5 分钟）..." -ForegroundColor Cyan
& $py -X utf8 (Join-Path $root "build\build_all.py") --sidecar
if ($LASTEXITCODE -ne 0) {
    throw "sidecar 构建失败（退出码 $LASTEXITCODE）。完整日志：build\_build_all.log"
}

Write-Host "[2/2] 校验产物..." -ForegroundColor Cyan
$out = Join-Path $root "build\out\legal-workbench"
$exe = Join-Path $out "legal-workbench.exe"
if (-not (Test-Path $exe)) {
    throw "未找到 $exe —— 构建可能静默失败，请查看 build\_build_all.log 与 build\_pyi_build.log"
}
if (-not (Test-Path (Join-Path $out "_internal\integrity.json"))) {
    Write-Host "! 缺少 _internal\integrity.json（完整性清单），发行包启动时会跳过校验" -ForegroundColor Yellow
}
$size = [math]::Round(((Get-ChildItem $out -Recurse -File | Measure-Object Length -Sum).Sum / 1MB), 1)
Write-Host "sidecar 就绪：$exe（$size MB）" -ForegroundColor Green
Write-Host "可直接运行 tools\build_tauri.ps1 打安装包。" -ForegroundColor Green
