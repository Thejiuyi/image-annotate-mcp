"""Build the Agensi submission zip and validate it against their checklist.

    python listing/agensi/build.py

The zip must contain a single top-level folder with SKILL.md at its root, text files
only, no symlinks, no OS hidden files. Every rule here comes from their creator
checklist; the point of the script is that a rejection should cost you a rerun, not a
24-hour review cycle.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "image-annotate"
DIST = HERE / "dist"

TOP = "image-annotate"
TEXT_SUFFIXES = {".md", ".py", ".txt", ".json", ".yaml", ".yml", ".sh", ".toml", ".cfg"}


def version() -> str:
    pyproject = HERE.parents[1] / "pyproject.toml"
    match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject.read_text(encoding="utf-8"), re.M)
    if not match:
        raise SystemExit(f"从 {pyproject} 里读不到版本号")
    return match.group(1)


def frontmatter(text: str) -> dict[str, str]:
    match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not match:
        raise SystemExit("SKILL.md 开头没有 YAML frontmatter")
    out: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            out[key.strip()] = value.strip()
    return out


def collect() -> list[Path]:
    files = sorted(p for p in SRC.rglob("*") if p.is_file())
    problems: list[str] = []

    for path in files:
        rel = path.relative_to(SRC)
        if any(part.startswith(".") for part in rel.parts):
            problems.append(f"隐藏文件: {rel}")
        if path.is_symlink():
            problems.append(f"符号链接: {rel}")
        if path.suffix.lower() not in TEXT_SUFFIXES:
            problems.append(f"非文本类型: {rel} ({path.suffix})")
            continue
        try:
            path.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            problems.append(f"不是 UTF-8 文本: {rel}")

    if not (SRC / "SKILL.md").is_file():
        problems.append("SKILL.md 不在包的根目录")
    else:
        meta = frontmatter((SRC / "SKILL.md").read_text(encoding="utf-8"))
        name = meta.get("name", "")
        desc = meta.get("description", "")
        if not re.fullmatch(r"[a-z0-9-]{1,64}", name):
            problems.append(f"name 不合规: {name!r}（只能小写字母/数字/连字符）")
        if name != TOP:
            problems.append(f"name ({name}) 和顶层文件夹名 ({TOP}) 不一致")
        if not desc:
            problems.append("description 是空的")
        elif len(desc) > 1024:
            problems.append(f"description {len(desc)} 字，超过 1024")

    if problems:
        print("包不合规，先修这些：")
        for p in problems:
            print(f"  ✗ {p}")
        raise SystemExit(1)

    # 清单里要求「至少一个参考文件或示例」
    if not (SRC / "references").is_dir() and not (SRC / "examples").is_dir():
        raise SystemExit("缺 references/ 或 examples/ —— 他们的清单要求至少一份支撑材料")

    return files


def main() -> int:
    files = collect()
    DIST.mkdir(exist_ok=True)
    out = DIST / f"{TOP}-{version()}.zip"
    if out.exists():
        out.unlink()

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            arc = Path(TOP) / path.relative_to(SRC)
            zf.write(path, arc.as_posix())

    # 回读校验：写到磁盘的东西才作数
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        tops = {n.split("/")[0] for n in names}
        assert tops == {TOP}, f"zip 顶层不止一个文件夹: {tops}"
        assert f"{TOP}/SKILL.md" in names, "zip 里没有 SKILL.md"

    print(f"\n{out.relative_to(HERE.parents[1])}  ({out.stat().st_size / 1024:.1f} KB)")
    for name in names:
        print(f"  {name}")
    print(f"\n{len(names)} 个文件，全部文本，单顶层文件夹 —— 可以直接上传。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
