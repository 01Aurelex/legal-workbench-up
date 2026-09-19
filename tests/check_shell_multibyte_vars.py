# -*- coding: utf-8 -*-
"""钉住一个只在 macOS CI 上暴露的坑：`$var` 后面紧跟非 ASCII 字符。

为什么需要这个测试
------------------
macOS runner 上 `shell: bash` 用的**不是** Homebrew 的 bash 5.x，而是
`/bin/bash --noprofile --norc -e -o pipefail`，即 **bash 3.2**。
bash 3.2 扫描变量名时会把 `$tag（` 里全角括号 `（` 的首字节吃进变量名，
于是

    echo "release tag = $tag（版本 $ver）"

被解析成「引用未定义变量 `$tag（版本`」，在 `set -u` 下直接

    line 8: tag?: unbound variable
    ##[error]Process completed with exit code 1.

判死整个脚本 —— 而这行往往排在真正的业务命令之前，表现为：
**步骤 1 秒失败、没有任何 ::error:: 注解、仓库里没有产生任何东西**，
极难从现象反推原因（本项目在 macOS 发布步骤上连查了 7 轮 CI）。

为什么必须做成静态扫描
--------------------
· `bash -n` 语法检查**查不出来**（语法本身合法）；
· 本机 Git Bash 是 bash 5.x，**复现不出来**；
· 只有 macOS 的 /bin/bash 3.2 + 全角字符同时出现才会触发。

修法：写成 `${tag}`（花括号定界，两种 bash 都安全）。

只扫代码行，跳过以 `#` 开头的注释行 —— 注释不会被执行，而且本仓库多处注释
就是在**举例说明**这个坑（写了 `$tag（` 这种反例），不跳过会自己误报自己。

用法
----
    python tests/check_shell_multibyte_vars.py [仓库根目录]
命中即退出码 1。
"""
from __future__ import annotations

import pathlib
import re
import sys

# $name 后面没有 } 且紧跟一个非 ASCII 字节
PAT = re.compile(rb"\$[A-Za-z_][A-Za-z0-9_]*(?=[\x80-\xff])")

EXTS = {".sh", ".bash", ".yml", ".yaml"}
SKIP_DIRS = {
    ".git", "node_modules", "out", "dist", "__pycache__", "target",
    "venv", ".venv", ".workbuddy",
}
MAX_SHOW = 40


def scan(root: pathlib.Path) -> tuple[int, list[str]]:
    hits: list[str] = []
    scanned = 0
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in EXTS:
            continue
        if any(part in SKIP_DIRS or part.startswith("_stripped") for part in p.parts):
            continue
        scanned += 1
        raw = p.read_bytes()
        for idx, line in enumerate(raw.split(b"\n"), start=1):
            if line.lstrip().startswith(b"#"):
                continue          # 注释行不执行，且常被用来举反例
            for m in PAT.finditer(line):
                snippet = line.decode("utf-8", "replace").strip()
                hits.append("%s:%d  %s   |  %s"
                            % (p.relative_to(root).as_posix(), idx,
                               m.group().decode("utf-8", "replace"), snippet[:140]))
    return scanned, hits


def main() -> int:
    root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    scanned, hits = scan(root)
    print("扫描 %d 个脚本/工作流文件（%s）" % (scanned, root))
    if not hits:
        print("OK：没有发现「$var 后紧跟非 ASCII 字符」的写法")
        return 0
    print("")
    print("发现 %d 处高危写法（macOS 的 /bin/bash 3.2 下会 unbound variable）：" % len(hits))
    for h in hits[:MAX_SHOW]:
        print("  " + h)
    if len(hits) > MAX_SHOW:
        print("  … 其余 %d 处省略" % (len(hits) - MAX_SHOW))
    print("")
    print("修法：把 $var 写成 ${var}，例如 $tag（版本 -> ${tag}（版本")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
