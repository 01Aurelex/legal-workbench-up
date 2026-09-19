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

# 本脚本（尤其是 [2/2] 校验）自己的输出在 CI 上只有仓库管理员能看
# （REST /logs 需要 admin 权限），所以全部落一份到 build/_sidecar_sh.log，
# 由 tools/ci_dump_build_log.py 在失败时转成公开可读的注解。
SHLOG="$ROOT/build/_sidecar_sh.log"
: >"$SHLOG" 2>/dev/null || true
say() { echo "$@" | tee -a "$SHLOG"; }

# 出错/退出都留痕：CI 上本脚本的 stdout 读不到，只有落盘的这几行能告诉我们
# 「到底死在哪一行、退出码是多少」。曾因为少了这个，白白多跑了两轮 CI。
# 这里刻意不用 say()（不经管道），避免 trap 自身再触发一次管道失败。
#
# ⚠️ LW_DONE 是必须的：bash 3.2（macOS runner 的 /bin/bash）在 unbound variable
# 这条路径上，进入 EXIT trap 时 $? 已经是 0，于是 EXIT trap 会把「脚本中途死掉」
# 上报成成功。实测：`set -u` + `$var（全角` → 脚本死在那一行，但带 EXIT trap 时
# 整个进程退出码为 0（不带 trap 才是 1）。所以这里用「没走到最后一行就不算成功」
# 兜住：只有脚本真正执行到末尾才会置 LW_DONE=1。
LW_DONE=0
trap 'rc=$?; if [ "$LW_DONE" -ne 1 ] && [ "$rc" -eq 0 ]; then rc=1; fi
      echo "!! 脚本在第 $LINENO 行失败，退出码 $rc" >>"$SHLOG" 2>/dev/null || true' ERR
trap 'rc=$?; if [ "$LW_DONE" -ne 1 ] && [ "$rc" -eq 0 ]; then rc=1; fi
      echo "== 脚本结束，退出码 $rc ==" >>"$SHLOG" 2>/dev/null || true
      exit "$rc"' EXIT

say "[1/2] 构建 sidecar（Cython 原生化 + PyInstaller，首次或全量重编约 5-15 分钟）..."
# 显式接住退出码：CI 上这一步的 stdout 只有管理员能看，所以退出码必须落进
# _sidecar_sh.log，否则失败时外面只看到 "Process completed with exit code 1"。
set +e
"$PY" -X utf8 build/build_all.py --sidecar
BUILD_RC=$?
set -e
say "[1/2] build_all.py 退出码 = $BUILD_RC"
if [ "$BUILD_RC" -ne 0 ]; then
    say "!! 构建失败，退出码 ${BUILD_RC}（详见 build/_build_all.log 与 build/_pyi_build.log）"
    exit "$BUILD_RC"
fi

say "[2/2] 校验产物..."
OUT="$ROOT/build/out/legal-workbench"
EXE="$OUT/legal-workbench"

{
    echo "=== [2/2] 校验产物 @ $(date -u +%FT%TZ) ==="
    echo "期望的可执行文件: $EXE"
    echo "--- ls -la $ROOT/build/out ---"
    ls -la "$ROOT/build/out" 2>&1 || true
    echo "--- ls -la $OUT ---"
    ls -la "$OUT" 2>&1 || true
    echo "--- 顶层可执行文件（排除 .so/.dylib）---"
    find "$OUT" -maxdepth 1 -type f -perm -u+x \
        ! -name '*.so' ! -name '*.dylib' 2>&1 || true
    echo "--- 全树名为 legal-workbench* 的文件 ---"
    find "$OUT" -maxdepth 4 -name 'legal-workbench*' 2>&1 || true
} >>"$SHLOG" 2>&1 || true

if [ ! -f "$EXE" ]; then
    say "!! 未找到 ${EXE}（-f 判定失败）"
    say "   若上面 ls 里存在同名文件，说明是权限/符号链接差异；否则是命名不符预期"
    exit 1
fi
say "  -f \$EXE 通过"

if [ ! -x "$EXE" ]; then
    chmod +x "$EXE"
    say "  -x 未通过，已补上可执行权限：$EXE"
else
    say "  -x \$EXE 通过"
fi

if [ ! -f "$OUT/_internal/integrity.json" ]; then
    say "  ! 缺少 _internal/integrity.json（完整性清单），发行包启动时会跳过校验"
else
    say "  integrity.json 就位"
fi

# 体积统计：用 Python 而不是 `du | awk`。
# 曾在这行踩坑：`du -sm X | awk ...` 在 runner 上既没输出也没让脚本走到下一行
# （日志停在上一句），配合 set -e/-o pipefail 直接判失败。
# Python 是既有依赖，且不受管道/退出码影响。
SIZE_MB="$("$PY" -c "import os,sys;t=0
for r,_d,fs in os.walk(sys.argv[1]):
    for x in fs:
        try: t+=os.path.getsize(os.path.join(r,x))
        except OSError: pass
print('%.1f'%(t/1048576.0))" "$OUT" 2>/dev/null || true)"
say "sidecar 就绪：${EXE}（约 ${SIZE_MB:-?} MB）"
say "可直接运行 tools/build_tauri.sh 打包 .app / .dmg。"

# 走到这里才算真成功（见上方 LW_DONE 的说明：bash 3.2 会把中途死亡上报成成功）
LW_DONE=1
