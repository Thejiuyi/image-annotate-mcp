"""Assemble out/gif/frame-*.png into docs/demo.gif.

    python tests/manual/make_gif.py

Frames come from tests/manual/make_gif.mjs. The last frame is held longer so the
"已保存" state is readable, and the sequence loops.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
FRAMES = HERE / "out" / "gif"
TARGET = HERE.parents[1] / "docs" / "demo.gif"
WIDTH = 900


def main() -> int:
    paths = sorted(FRAMES.glob("frame-*.png"))
    if not paths:
        print(f"没有帧：{FRAMES}。先跑 node tests/manual/make_gif.mjs <url>")
        return 1

    images = []
    for path in paths:
        img = Image.open(path).convert("RGB")
        height = round(img.height * WIDTH / img.width)
        images.append(img.resize((WIDTH, height), Image.LANCZOS))

    # quantise to a shared palette so the GIF stays small
    # 界面几乎是纯色块，抖动只会把体积撑大、画质还更脏
    palette = images[0].quantize(colors=96, method=Image.MEDIANCUT)
    frames = [im.quantize(palette=palette, dither=Image.NONE) for im in images]

    durations = [700] * (len(frames) - 1) + [1800]
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(
        TARGET,
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
        optimize=True,
    )
    size_kb = TARGET.stat().st_size / 1024
    print(f"{TARGET}  {len(frames)} 帧  {size_kb:.0f} KB  {frames[0].width}×{frames[0].height}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
