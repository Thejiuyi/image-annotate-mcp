"""Turn a saved annotation into things a program can consume.

Four formats:

* ``png``  -- the base image with every item numbered and outlined, for a
  multimodal agent to *look at* instead of reading a table.
* ``py``   -- coordinate constants + a template map, ready to paste into code.
* ``json`` -- the structured payload, copied into ``exports/``.
* ``yaml`` -- same content, for configs (no PyYAML dependency).

The png renderer prefers the snapshot we took at save time, so it still works
after the original screenshot is gone.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import store

__all__ = ["render_annotated", "constants_py", "export"]

_BOX_COLOR = (255, 95, 109)
_POINT_COLOR = (255, 209, 102)
_POLY_COLOR = (126, 231, 135)
_UNDER = (0, 0, 0)
_LABEL_BG = (24, 26, 32)
_LABEL_FG = (255, 255, 255)


def _font(size: int) -> ImageFont.ImageFont:
    # CJK-capable faces first: the labels are usually Chinese, and a Latin-only
    # font would render them as blank boxes.
    for name in (
        "msyh.ttc",
        "msyhl.ttc",
        "simhei.ttf",
        "PingFang.ttc",
        "Hiragino Sans GB.ttc",
        "NotoSansCJK-Regular.ttc",
        "NotoSansSC-Regular.otf",
        "wqy-microhei.ttc",
        "DejaVuSans.ttf",
        "arial.ttf",
    ):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


def _base_image(payload: dict, image: dict) -> Image.Image:
    snapshot = image.get("snapshot")
    if snapshot:
        path = store.sources_dir() / snapshot
        if path.is_file():
            img = Image.open(path)
            img.load()
            return img
    source = str(image.get("source") or "")
    if source.startswith("file:"):
        path = Path(source[5:])
        if path.is_file():
            img = Image.open(path)
            img.load()
            return img
    raise FileNotFoundError(
        f"图片 {image.get('id')} 的底图找不到了（source={source or '未知'}，"
        f"快照={snapshot or '无'}）。改用 annotate_export(fmt='json') 拿坐标，"
        "或者重新开一个标注会话让用户再标一次。"
    )


def _points(item: dict) -> list[tuple[int, int]]:
    """Polygon vertices as int tuples; PIL rejects floats in some builds."""
    return [(int(p[0]), int(p[1])) for p in item.get("points") or []]


def render_annotated(
    payload: dict, image_id: str | None = None, out_dir: Path | None = None
) -> Path:
    """Draw numbered outlines over one image and save it as a PNG."""
    images = payload.get("images") or []
    if not images:
        raise ValueError("这份标注里没有图片。")
    if image_id is None:
        image = images[0]
    else:
        matches = [im for im in images if im.get("id") == image_id]
        if not matches:
            raise ValueError(
                f"没有图片 {image_id!r}；这份标注里有 {[im.get('id') for im in images]}。"
            )
        image = matches[0]

    base = _base_image(payload, image).convert("RGB")
    width, height = base.size
    stroke = max(2, round(min(width, height) / 400))
    font = _font(max(12, round(min(width, height) / 45)))

    # Hidden items stay out of the picture but keep their template on disk: the eye
    # button means "get out of my way while I look at the screenshot", not "delete".
    visible = [it for it in (image.get("items") or []) if not it.get("hidden")]

    # Polygon tints go onto a separate overlay and get composited in one pass.
    # A translucent fill drawn straight onto an RGB image would paint over the
    # screenshot instead of tinting it.
    tints = [it for it in visible if it.get("type") == "polygon"]
    if tints:
        overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
        odraw = ImageDraw.Draw(overlay)
        for it in tints:
            odraw.polygon(_points(it), fill=(*_POLY_COLOR, 40))
        base = Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB")

    draw = ImageDraw.Draw(base)
    for item in visible:
        number = str(item.get("index", ""))
        label = f"{number} {item.get('name', '')}".strip()
        kind = item.get("type")
        if kind == "box":
            x, y, w, h = item["box"]
            # dark under-stroke first: a red outline on a red button is invisible
            draw.rectangle([x, y, x + w, y + h], outline=_UNDER, width=stroke + 4)
            draw.rectangle([x, y, x + w, y + h], outline=_BOX_COLOR, width=stroke)
            _draw_label(draw, (x, y), label, font, _BOX_COLOR)
        elif kind == "polygon":
            pts = _points(item)
            draw.polygon(pts, outline=_UNDER, width=stroke + 4)
            draw.polygon(pts, outline=_POLY_COLOR, width=stroke)
            _draw_label(draw, pts[0], label, font, _POLY_COLOR)
        else:
            px, py = item["point"]
            r = max(10, stroke * 5)
            for colour, extra in ((_UNDER, 4), (_POINT_COLOR, 0)):
                draw.ellipse([px - r, py - r, px + r, py + r], outline=colour, width=stroke + extra)
                draw.line([px - r * 2, py, px + r * 2, py], fill=colour, width=stroke + extra)
                draw.line([px, py - r * 2, px, py + r * 2], fill=colour, width=stroke + extra)
            _draw_label(draw, (px + r, py - r), label, font, _POINT_COLOR)

    target_dir = out_dir or store.exports_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    slug = store.ascii_slug(payload.get("name", ""), "board_ui")
    path = target_dir / f"{slug}__{image.get('id', 'img1')}__annotated.png"
    base.save(path, format="PNG")
    return path


def _draw_label(
    draw: ImageDraw.ImageDraw, anchor: tuple[int, int], text: str, font, accent
) -> None:
    if not text:
        return
    x, y = anchor
    try:
        left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    except Exception:  # noqa: BLE001 - bitmap fallback fonts can be quirky
        left, top, right, bottom = 0, 0, len(text) * 6, 12
    pad = 4
    box_w = right - left + pad * 2
    box_h = bottom - top + pad * 2
    bx = max(0, min(x, draw.im.size[0] - box_w))
    by = max(0, y - box_h - 2)
    draw.rectangle([bx, by, bx + box_w, by + box_h], fill=_LABEL_BG, outline=accent, width=1)
    draw.text((bx + pad - left, by + pad - top), text, fill=_LABEL_FG, font=font)


def _ident(text: str, fallback: str) -> str:
    """ASCII-only Python identifier; the Chinese name travels in a comment instead."""
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", text or "").strip("_")
    if not cleaned:
        cleaned = fallback
    if cleaned[0].isdigit():
        cleaned = "_" + cleaned
    return cleaned


def constants_py(payload: dict, prefix: str | None = None) -> str:
    """Generate a Python module with coordinate constants and the template map."""
    stem = prefix or store.ascii_slug(payload.get("name", ""), "board_ui").upper()
    lines = [
        '"""Generated by image-annotate-mcp -- do not edit by hand.',
        "",
        f"source : {payload.get('name', '')}.json",
        f"saved_at: {payload.get('saved_at', '')}",
        '"""',
        "",
        "from __future__ import annotations",
        "",
    ]
    used: set[str] = set()

    for image in payload.get("images") or []:
        iid = _ident(image.get("id", "img1"), "img").upper()
        size = image.get("size") or [0, 0]
        name = _unique_ident(f"{stem}_{iid}_SIZE", used)
        lines.append(f"{name} = ({size[0]}, {size[1]})")

    lines.append("")

    for image in payload.get("images") or []:
        iid = _ident(image.get("id", "img1"), "img").upper()
        for item in image.get("items") or []:
            fallback = "item" + str(item.get("index"))
            name = _unique_ident(
                f"{stem}_{iid}_{_ident(item.get('name', ''), fallback).upper()}", used
            )
            label = item.get("name", "")
            if item.get("type") == "box":
                x, y, w, h = item["box"]
                lines.append(f"{name} = ({x}, {y}, {w}, {h})  # {label} · x, y, w, h")
            elif item.get("type") == "polygon":
                pts = ", ".join(f"({int(p[0])}, {int(p[1])})" for p in item["points"])
                lines.append(f"{name} = [{pts}]  # {label} · 多边形 {len(item['points'])} 个顶点")
            else:
                px, py = item["point"]
                lines.append(f"{name} = ({px}, {py})  # {label} · x, y")
    lines.append("")

    templates: dict[str, dict[str, str]] = {}
    display: dict[str, str] = {}
    for image in payload.get("images") or []:
        for item in image.get("items") or []:
            template = item.get("template")
            if not template:
                continue
            key = _ident(item.get("name", ""), "item" + str(item.get("index"))).lower()
            templates.setdefault(image.get("id", "img1"), {})[key] = template
            display[key] = item.get("name", "")
    if templates:
        lines.append(f"{stem}_TEMPLATES = {{")
        for iid, mapping in templates.items():
            lines.append(f"    {iid!r}: {{")
            for key, value in mapping.items():
                lines.append(f"        {key!r}: {value!r},  # {display.get(key, '')}")
            lines.append("    },")
        lines.append("}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _unique_ident(candidate: str, used: set[str]) -> str:
    name = candidate
    n = 2
    while name in used:
        name = f"{candidate}_{n}"
        n += 1
    used.add(name)
    return name


def _yaml_scalar(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if value is None:
        return "null"
    text = str(value)
    if text == "" or re.search(r"[:#\[\]{},&*?|<>=!%@`\"']", text) or text != text.strip():
        return json.dumps(text, ensure_ascii=False)
    return text


def to_yaml(value, indent: int = 0) -> str:
    pad = " " * indent
    if isinstance(value, dict):
        if not value:
            return "{}"
        out = []
        for key, item in value.items():
            key_text = _yaml_scalar(key)
            if isinstance(item, (dict, list)) and item:
                out.append(f"{pad}{key_text}:")
                out.append(to_yaml(item, indent + 2))
            else:
                out.append(f"{pad}{key_text}: {to_yaml(item, 0)}")
        return "\n".join(out)
    if isinstance(value, list):
        if not value:
            return "[]"
        out = []
        for item in value:
            if isinstance(item, (dict, list)) and item:
                nested = to_yaml(item, indent + 2)
                out.append(f"{pad}- {nested.lstrip()}")
            else:
                out.append(f"{pad}- {to_yaml(item, 0)}")
        return "\n".join(out)
    return _yaml_scalar(value)


def export(
    name: str,
    fmt: str = "png",
    out_dir: str | Path | None = None,
    image_id: str | None = None,
) -> dict:
    """Export one saved annotation. Returns ``{ok, files, constants}``."""
    payload = store.load_annotation(name)
    slug = store.ascii_slug(payload.get("name", ""), "board_ui")
    target_dir = Path(out_dir).expanduser() if out_dir else store.exports_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    fmt = (fmt or "png").lower().strip()

    if fmt == "png":
        path = render_annotated(payload, image_id=image_id, out_dir=target_dir)
        return {"ok": True, "format": "png", "files": [str(path)], "constants": None}

    if fmt == "py":
        text = constants_py(payload)
        path = target_dir / f"{slug}_constants.py"
        path.write_text(text, encoding="utf-8")
        return {"ok": True, "format": "py", "files": [str(path)], "constants": text}

    if fmt == "json":
        path = target_dir / f"{slug}.json"
        clean = {k: v for k, v in payload.items() if not k.startswith("_")}
        path.write_text(json.dumps(clean, ensure_ascii=False, indent=1), encoding="utf-8")
        return {"ok": True, "format": "json", "files": [str(path)], "constants": None}

    if fmt in ("yaml", "yml"):
        path = target_dir / f"{slug}.yaml"
        clean = {k: v for k, v in payload.items() if not k.startswith("_")}
        path.write_text(to_yaml(clean) + "\n", encoding="utf-8")
        return {"ok": True, "format": "yaml", "files": [str(path)], "constants": None}

    raise ValueError(f"不支持的 fmt={fmt!r}；可用的是 png / py / json / yaml。")
