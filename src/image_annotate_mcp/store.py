"""Where annotations land on disk.

Layout (default ``~/.image-annotate-mcp``, override with ``IMAGE_ANNOTATE_DATA_DIR``)::

    <data>/annotations/<slug>.json     structured, this is the source of truth
    <data>/annotations/<slug>.md       human/agent readable table
    <data>/templates/<slug>__<img>__<item>.png    one crop per box
    <data>/exports/                    annotated previews and code constants

Re-saving the same session name overwrites the JSON/MD and the templates of the
items that still exist; stale template files from deleted items are left alone on
purpose (deleting user data to tidy up is not worth the risk).
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw

from .sessions import Session, polygon_bbox

__all__ = [
    "data_dir",
    "annotations_dir",
    "templates_dir",
    "exports_dir",
    "sources_dir",
    "ascii_slug",
    "save_session",
    "load_annotation",
    "list_annotations",
    "annotation_path",
]

_DEFAULT_DIR = Path.home() / ".image-annotate-mcp"


def data_dir() -> Path:
    env = os.environ.get("IMAGE_ANNOTATE_DATA_DIR")
    return Path(env).expanduser() if env else _DEFAULT_DIR


def annotations_dir() -> Path:
    return data_dir() / "annotations"


def templates_dir() -> Path:
    return data_dir() / "templates"


def exports_dir() -> Path:
    return data_dir() / "exports"


def sources_dir() -> Path:
    return data_dir() / "sources"


def ascii_slug(text: str, fallback: str = "item") -> str:
    """ASCII-only file stem.

    Pillow itself handles Unicode paths fine -- unlike OpenCV, whose non-ASCII
    path bugs the original prototype had to dodge. We keep ASCII anyway because
    these filenames end up inside generated Python constants and configs, where
    ASCII travels better. The Chinese name still lives in the JSON/Markdown.
    """
    slug = re.sub(r"[^A-Za-z0-9-]+", "_", text or "").strip("_").lower()
    return slug[:60] or fallback


def _unique(name: str, used: set[str]) -> str:
    if name not in used:
        used.add(name)
        return name
    n = 2
    while f"{name}_{n}" in used:
        n += 1
    final = f"{name}_{n}"
    used.add(final)
    return final


def _snapshot(img, directory: Path, filename: str) -> str | None:
    """Keep a copy of the base image so exports still work when the original is gone."""
    try:
        img.save(directory / filename, format="PNG")
    except Exception as exc:  # noqa: BLE001 - degraded export beats a failed save
        print(f"[image-annotate-mcp] 底图快照写入失败：{exc!r}", file=sys.stderr)
        return None
    return filename


def _polygon_crop(img, points: list[list[int]]):
    """Crop the vertex bbox, then keep only the pixels inside the outline.

    Everything outside becomes fully transparent, so the template is the irregular
    region itself rather than its bounding rectangle -- that is the entire reason
    for offering a polygon tool.
    """
    x, y, w, h = polygon_bbox(points)
    region = img.crop((x, y, x + w, y + h)).convert("RGBA")
    mask = Image.new("L", region.size, 0)
    ImageDraw.Draw(mask).polygon([(px - x, py - y) for px, py in points], fill=255)
    region.putalpha(mask)
    return region


def save_session(session: Session) -> dict:
    """Write JSON + Markdown + template crops for the session's current state."""
    ann_dir = annotations_dir()
    tpl_dir = templates_dir()
    src_dir = sources_dir()
    ann_dir.mkdir(parents=True, exist_ok=True)
    tpl_dir.mkdir(parents=True, exist_ok=True)
    src_dir.mkdir(parents=True, exist_ok=True)

    slug = ascii_slug(session.name, "board_ui")
    images_payload = []
    made: list[str] = []

    for iid in session.order:
        entry = session.images[iid]
        width, height = entry.size
        used: set[str] = set()
        out_items = []
        for item in session.items.get(iid, []):
            rec = dict(item)
            crop = None
            if rec.get("type") == "box":
                x, y, w, h = rec["box"]
                crop = entry.image.crop((x, y, x + w, y + h))
            elif rec.get("type") == "polygon":
                crop = _polygon_crop(entry.image, rec["points"])
            if crop is not None:
                item_slug = ascii_slug(rec["name"], "item" + str(rec["index"]))
                stem = _unique(f"{slug}__{iid}__{item_slug}", used)
                filename = f"{stem}.png"
                crop.save(tpl_dir / filename, format="PNG")
                rec["template"] = filename
                made.append(filename)
            out_items.append(rec)
        # Keep the in-memory items and the file identical, template names included,
        # so annotate_wait can hand the agent a complete record in one call.
        session.set_items(iid, out_items)
        images_payload.append(
            {
                "id": iid,
                "name": entry.name,
                "source": entry.source,
                "size": [width, height],
                "snapshot": _snapshot(entry.image, src_dir, f"{slug}__{iid}.png"),
                "items": out_items,
            }
        )

    payload = {
        "schema": 2,
        "name": session.name,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(session.created)),
        "saved_at": session.saved_at or time.strftime("%Y-%m-%d %H:%M:%S"),
        "rev": session.rev,
        "images": images_payload,
    }
    json_path = ann_dir / f"{slug}.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    md_path = ann_dir / f"{slug}.md"
    md_path.write_text(_to_markdown(payload), encoding="utf-8")

    return {
        "ok": True,
        "dir": str(ann_dir),
        "json": str(json_path),
        "markdown": str(md_path),
        "templates": made,
        "templates_dir": str(tpl_dir),
        "items": sum(len(img["items"]) for img in images_payload),
    }


def _to_markdown(payload: dict) -> str:
    lines = [
        f"# 标注：{payload.get('name', '')}",
        "",
        f"- 时间：{payload.get('saved_at', '')}",
        f"- 图片：{len(payload.get('images', []))} 张",
        "",
    ]
    for img in payload.get("images", []):
        size = img.get("size") or [0, 0]
        lines.append(f"## {img.get('id')} · {img.get('name')}（{size[0]}×{size[1]}）")
        lines.append("")
        if not img.get("items"):
            lines.append("_（这张图还没有标注）_")
            lines.append("")
            continue
        lines.append("| # | 名称 | 类型 | 坐标 | 模板 |")
        lines.append("|---|---|---|---|---|")
        for it in img["items"]:
            if it.get("type") == "box":
                x, y, w, h = it["box"]
                coord = f"x {x} y {y} {w}×{h}"
                kind = "框选"
            elif it.get("type") == "polygon":
                bx, by, bw, bh = it.get("bbox") or polygon_bbox(it["points"])
                coord = f"{len(it['points'])} 点 · bbox x {bx} y {by} {bw}×{bh}"
                kind = "多边形"
            else:
                coord = f"({it['point'][0]}, {it['point'][1]})"
                kind = "点选"
            if it.get("hidden"):
                kind += "·隐藏"
            lines.append(
                f"| {it.get('index')} | {it.get('name')} | {kind} | {coord} | "
                f"`{it.get('template', '')}` |"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# -- reading back -------------------------------------------------------


def _upcast_v1(payload: dict) -> dict:
    """Old single-image files (the prototype's format) are read, never rewritten."""
    if "schema" in payload and "images" in payload:
        return payload
    return {
        "schema": 2,
        "name": payload.get("name") or "board_ui",
        "created_at": payload.get("saved_at"),
        "saved_at": payload.get("saved_at"),
        "rev": 1,
        "upcast_from": 1,
        "images": [
            {
                "id": "img1",
                "name": payload.get("image") or "img1",
                "source": payload.get("image") or "",
                "size": payload.get("size") or [0, 0],
                "items": payload.get("items") or [],
            }
        ],
    }


def annotation_path(name: str) -> Path:
    """Resolve ``name`` (file, slug, or display name) to a JSON path."""
    candidate = Path(name).expanduser()
    if candidate.is_file():
        return candidate
    ann_dir = annotations_dir()
    direct = ann_dir / f"{ascii_slug(name, '')}.json"
    if direct.is_file():
        return direct
    if ann_dir.is_dir():
        for path in sorted(ann_dir.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if payload.get("name") == name:
                return path
    available = [p.stem for p in sorted(ann_dir.glob("*.json"))] if ann_dir.is_dir() else []
    raise FileNotFoundError(
        f"找不到标注 {name!r}。{ann_dir} 里现有：{available or '（空）'}。"
        "先调 annotate_list 看看有哪些。"
    )


def load_annotation(name: str) -> dict:
    path = annotation_path(name)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload = _upcast_v1(payload)
    payload["_path"] = str(path)
    return payload


def list_annotations(limit: int = 20) -> list[dict]:
    ann_dir = annotations_dir()
    if not ann_dir.is_dir():
        return []
    rows = []
    for path in ann_dir.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        payload = _upcast_v1(payload)
        images = payload.get("images") or []
        rows.append(
            {
                "name": payload.get("name") or path.stem,
                "slug": path.stem,
                "saved_at": payload.get("saved_at"),
                "images": len(images),
                "items": sum(len(img.get("items") or []) for img in images),
                "path": str(path),
            }
        )
    rows.sort(key=lambda r: (r.get("saved_at") or "", r["slug"]), reverse=True)
    return rows[: max(0, int(limit))]
