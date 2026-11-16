"""Manual end-to-end check for wheel zoom / pan / the loupe.

    python tests/manual/e2e_view.py

Opens a session on a synthetic screenshot, lets ``verify_view.mjs`` drive Edge
with a real mouse and a real wheel, then checks that what got saved matches what
the page claimed was under the cursor. Exits non-zero on any mismatch.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
SRC = HERE.parents[1] / "src"


def _node() -> str:
    """node 在哪都行：PATH 优先，其次 NODE_BIN 环境变量。"""
    found = shutil.which("node") or shutil.which("node.exe")
    if found:
        return found
    env = os.environ.get("NODE_BIN")
    if env and Path(env).is_file():
        return env
    raise SystemExit(
        "找不到 node，无法驱动浏览器。装一个 Node.js（https://nodejs.org/），"
        "或用 NODE_BIN 指到 node 可执行文件。"
    )


def main() -> int:
    sys.path.insert(0, str(SRC))
    sys.path.insert(0, str(HERE))
    os.environ["IMAGE_ANNOTATE_DATA_DIR"] = str(OUT / "data")

    from e2e import build_sample

    from image_annotate_mcp import sessions

    sample = build_sample(OUT / "fake_ui.png", (1280, 720), (220, 80, 90))
    sessions.configure(base_port=8992, auto_open=False)
    manager = sessions.get_manager()
    session = manager.create(name="view_ui", sources=str(sample))
    print(f"URL {session.url}", flush=True)

    report_path = OUT / "view-report.json"
    # 先删掉上一轮的：node 半路崩掉时如果读到旧报告，就会拿旧的绿冒充新的绿
    if report_path.exists():
        report_path.unlink()
    proc = subprocess.run(
        [_node(), str(HERE / "verify_view.mjs"), session.url],
        capture_output=True,
        text=True,
        timeout=240,
    )
    if not report_path.is_file():
        print("浏览器这轮没写出报告，按失败处理。")
        print(proc.stdout[-3000:])
        print(proc.stderr[-3000:], file=sys.stderr)
        manager.close_all()
        return 1

    report = json.loads(report_path.read_text(encoding="utf-8"))
    result = session.wait(since_rev=0, timeout_s=30)
    manager.close_all()

    checks: list[tuple[str, bool, str]] = []

    def check(label: str, ok: bool, detail: str = "") -> None:
        checks.append((label, bool(ok), detail))

    for c in report["checks"]:
        check("[浏览器] " + c["label"], c["ok"], c["detail"])
    check("页面没有 JS 报错", not report["problems"], str(report["problems"]))

    if result["status"] != "saved":
        print(json.dumps({"status": result["status"]}, ensure_ascii=False))
        return 1

    items = result["images"][0]["items"]
    check("存下了三项", len(items) == 3, f"实际 {len(items)} 项")

    kinds = [it.get("type") for it in items]
    check("顺序是 点 / 框 / 点", kinds == ["point", "box", "point"], str(kinds))

    aimed = report["aimed"]

    def near(a, b, tol=1):
        return abs(a - b) <= tol

    if len(items) == 3 and aimed["point"]:
        ax, ay = aimed["point"]
        got = items[0].get("point") or [0, 0]
        check(
            "放大状态下点的坐标就是读数",
            near(got[0], ax) and near(got[1], ay),
            f"{got} vs {aimed['point']}",
        )

        (x0, y0), (x1, y1) = aimed["box"]
        expect = [min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0)]
        box = items[1].get("box") or [0, 0, 0, 0]
        ok = all(near(box[i], expect[i], 2) for i in range(4))
        check("放大状态下拖的框也对得上", ok, f"{box} vs {expect}")

        px, py = aimed["pointAfterPan"]
        got2 = items[2].get("point") or [0, 0]
        check(
            "平移之后点的坐标仍然对",
            near(got2[0], px) and near(got2[1], py),
            f"{got2} vs {aimed['pointAfterPan']}",
        )

    width = max(len(label) for label, _, _ in checks)
    failed = 0
    for label, ok, detail in checks:
        mark = "PASS" if ok else "FAIL"
        if not ok:
            failed += 1
        suffix = f"  <- {detail}" if detail and not ok else ""
        print(f"[{mark}] {label.ljust(width)}{suffix}")

    print()
    print(f"E2E={'PASS' if failed == 0 else 'FAIL'} ({len(checks) - failed}/{len(checks)})")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
