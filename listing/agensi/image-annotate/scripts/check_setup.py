#!/usr/bin/env python3
"""Read-only prerequisite check for the image-annotate skill.

Installs nothing, writes nothing, makes no network calls. It prints what is missing and
the exact command that fixes it, because "the tool does not exist" is not a useful error
message for the user.
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

PKG = "image_annotate_mcp"
DIST = "image-annotate-mcp"
SCRIPT = "annotate-mcp"
INSTALL = 'pip install "git+https://github.com/Thejiuyi/image-annotate-mcp"'
CONFIG = """{
  "mcpServers": {
    "image-annotate": { "command": "annotate-mcp", "args": [] }
  }
}"""


def installed_version() -> str | None:
    """Version of the installed distribution, without importing the package itself."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version(DIST)
    except PackageNotFoundError:
        return None


def module_present() -> bool:
    try:
        return importlib.util.find_spec(PKG) is not None
    except (ImportError, ValueError):
        return False


def console_script() -> str | None:
    """Where the console script lives, whether or not the venv is activated.

    ``shutil.which`` only sees PATH, so inside a venv that was never activated it reports
    the script as missing even though it sits right next to the interpreter. Checking the
    interpreter's own directory first is the difference between a real diagnosis and a
    false alarm.
    """
    for name in (SCRIPT, SCRIPT + ".exe", SCRIPT + ".cmd", SCRIPT + ".bat"):
        beside = Path(sys.executable).parent / name
        if beside.is_file():
            return str(beside)
    return shutil.which(SCRIPT)


def main() -> int:
    print(f"python      {sys.version.split()[0]}  ({sys.executable})")

    version = installed_version()
    print(f"package     {DIST} {version}" if version else f"package     {DIST} 未安装")

    exe = console_script()
    print(f"console     {exe}" if exe else f"console     {SCRIPT} 不在 PATH 上")

    problems: list[tuple[str, str]] = []
    # 这个检查是给「跑脚本的那个解释器」看的，不是给本项目的最低版本看的 ——
    # 用户很可能在系统自带的旧 Python 上跑它，所以要保留运行时判断。
    if sys.version_info < (3, 10):  # noqa: UP036
        problems.append(("Python 版本太低", "需要 3.10 或更新版本；先升级 Python。"))
    if not module_present():
        problems.append((f"{DIST} 没装", INSTALL))
    if not exe:
        problems.append((f"{SCRIPT} 不在 PATH 上", "装完包后重启终端；用虚拟环境的话先 activate。"))

    if not problems:
        print("\nOK：包和命令都在。接着确认 MCP 客户端里注册了这个 server，然后重启客户端：")
        print(CONFIG)
        return 0

    print()
    for what, action in problems:
        print(f"✗ {what}")
        print(f"  → {action}")
    print("\n装完之后，在客户端的 MCP 配置里加上：")
    print(CONFIG)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
