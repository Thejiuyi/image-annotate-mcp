"""Manual end-to-end check: real page, real mouse, real save.

Not part of pytest -- it needs a browser. Two halves:

    python tests/manual/e2e.py [--two]   # builds sample screenshots, opens a session,
                                         # waits for the save, writes out/result.json
    node   tests/manual/verify_page.mjs <url>
                                         # drives Edge: drags + clicks + rename + save

``--two`` opens a two-image session so the tabs / per-image items path gets used.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).with_name("out")


def build_sample(path: Path, size: tuple[int, int], accent: tuple[int, int, int]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    width, height = size
    img = Image.new("RGB", size, (18, 22, 34))
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, width, 56], fill=(30, 36, 52))
    draw.rectangle([0, height - 56, width, height], fill=(26, 31, 45))
    draw.ellipse([width - 300, 180, width - 160, 320], fill=(80, 210, 230))  # "crystal"
    draw.rounded_rectangle([width - 240, 520, width - 40, 600], radius=14, fill=accent)  # "attack"
    draw.rounded_rectangle([40, 520, 220, 600], radius=14, fill=(240, 190, 90))  # "shop"
    draw.rounded_rectangle(
        [int(width * 0.24), 200, int(width * 0.55), 480], radius=18, fill=(44, 52, 74)
    )  # "card"
    img.save(path)
    return path


def main() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
    from image_annotate_mcp import sessions, store

    two = "--two" in sys.argv
    first = build_sample(OUT / "fake_ui.png", (1280, 720), (220, 80, 90))
    sources = str(first)
    if two:
        second = build_sample(OUT / "fake_ui_2.png", (1024, 600), (150, 110, 230))
        sources = [str(first), str(second)]

    sessions.configure(base_port=8990, auto_open=False)
    manager = sessions.get_manager()
    session = manager.create(name="fake_ui", sources=sources)
    print(f"URL {session.url}", flush=True)
    print(f"SESSION {session.id}", flush=True)

    result = session.wait(since_rev=0, timeout_s=180)
    payload = {
        "status": result["status"],
        "rev": result["rev"],
        "saved_at": result["saved_at"],
        "images": result["images"],
        "written": None,
    }
    if result["status"] == "saved":
        # do NOT save again here: the HTTP /save already did it, and a second call
        # would hide whether the first one actually produced templates
        payload["written"] = {
            "json": str(store.annotations_dir() / f"{store.ascii_slug(session.name)}.json"),
            "templates": [
                it["template"]
                for img in result["images"]
                for it in img["items"]
                if it.get("template")
            ],
        }

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "result.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(json.dumps({"status": payload["status"], "rev": payload["rev"]}))
    manager.close_all()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
