"""Manual end-to-end check for the polygon tool + hidden-layer switches.

    python tests/manual/e2e_polygon.py

Opens a session on a synthetic screenshot, lets ``verify_polygon.mjs`` drive Edge
with a real mouse, then compares what was aimed at with what actually got saved.
Exits non-zero on any mismatch, so it works as a gate as well as a demo.
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
    # Keep this check self-contained: writing into the real ~/.image-annotate-mcp
    # would clobber a user annotation that happens to be called polygon_ui.
    os.environ["IMAGE_ANNOTATE_DATA_DIR"] = str(OUT / "data")

    from e2e import build_sample
    from PIL import Image

    from image_annotate_mcp import export, sessions, store

    sample = build_sample(OUT / "fake_ui.png", (1280, 720), (220, 80, 90))
    sessions.configure(base_port=8991, auto_open=False)
    manager = sessions.get_manager()
    session = manager.create(name="polygon_ui", sources=str(sample))
    print(f"URL {session.url}", flush=True)

    proc = subprocess.run(
        [_node(), str(HERE / "verify_polygon.mjs"), session.url],
        capture_output=True,
        text=True,
        timeout=180,
    )
    if proc.returncode != 0:
        print(proc.stdout[-3000:])
        print(proc.stderr[-3000:], file=sys.stderr)
        manager.close_all()
        return 1

    report = json.loads((OUT / "polygon-report.json").read_text(encoding="utf-8"))
    result = session.wait(since_rev=0, timeout_s=30)
    manager.close_all()

    checks: list[tuple[str, bool, str]] = []

    def check(label: str, ok: bool, detail: str = "") -> None:
        checks.append((label, bool(ok), detail))

    if result["status"] != "saved":
        print(json.dumps({"status": result["status"]}, ensure_ascii=False))
        return 1

    items = result["images"][0]["items"]
    check("保存了两项", len(items) == 2, f"实际 {len(items)} 项")

    poly = next((it for it in items if it.get("type") == "polygon"), None)
    box = next((it for it in items if it.get("type") == "box"), None)
    check("有 polygon 项", poly is not None)
    check("有 box 项", box is not None)

    if poly:
        aimed = [list(map(int, p)) for p in report["aimed"]["polygon"]]
        check("多边形顶点与瞄准点逐点一致", poly["points"] == aimed, f"{poly['points']} vs {aimed}")
        check("多边形带 bbox", poly.get("bbox") == [250, 200, 370, 320], str(poly.get("bbox")))
        # Two consumers render the same bbox: the sidebar text and the saved JSON.
        # If they disagree the user sees one number and the agent gets another.
        bx, by, bw, bh = poly.get("bbox") or (0, 0, 0, 0)
        shown = report["afterBox"][0]["coord"]
        expected = f"{len(poly['points'])} 点 · bbox x {bx} y {by} {bw}×{bh}"
        check("侧栏 bbox 文案与保存值一致", shown == expected, f"{shown!r} != {expected!r}")
        template = poly.get("template")
        check("多边形有模板文件", bool(template))
        if template:
            path = store.templates_dir() / template
            check("模板文件存在", path.is_file(), str(path))
            if path.is_file():
                tpl = Image.open(path)
                check("模板是 RGBA", tpl.mode == "RGBA", tpl.mode)
                check("模板按顶点 bbox 裁", tpl.size == (370, 320), str(tpl.size))
                # 顶点 bbox 的左上角在四边形之外 -> 必须被裁掉
                check(
                    "四边形外的角是透明的", tpl.getpixel((0, 0))[3] == 0, str(tpl.getpixel((0, 0)))
                )
                # 四边形内部保留原图像素
                check("四边形内是不透明的", tpl.getpixel((185, 160))[3] == 255)

    if box:
        aimed_box = [int(v) for v in report["aimed"]["box"]]
        check("框选坐标一致", box["box"] == aimed_box, f"{box['box']} vs {aimed_box}")
        check("眼睛按钮把 hidden 存下来了", box.get("hidden") is True, str(box.get("hidden")))
        check("隐藏项照样有模板", bool(box.get("template")))

    check("眼睛按钮图标变成 🚫", report["afterEye"][1]["eye"] == "🚫", report["afterEye"][1]["eye"])
    check("列表行变暗", report["afterEye"][1]["off"] is True)
    check(
        "全局隐藏后按钮文案变『显示标注』",
        "显示标注" in report["hideLabelOn"],
        report["hideLabelOn"],
    )
    check("canvas 挂上 hidden-layer", report["canvasHidden"] is True)
    check("再点一次恢复『隐藏标注』", "隐藏标注" in report["hideLabelOff"], report["hideLabelOff"])
    check("页面没有 JS 报错", not report["problems"], str(report["problems"]))

    # 渲染通道：隐藏项不该出现在导出的预览图里
    png = export.export("polygon_ui", fmt="png")["files"][0]
    rendered = Image.open(png).convert("RGB")
    bx, by, bw, bh = box["box"] if box else (0, 0, 0, 0)
    check(
        "导出图里隐藏的框没被画出来",
        rendered.getpixel((bx, by)) == (18, 22, 34),
        str(rendered.getpixel((bx, by))),
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
