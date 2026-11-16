"""Exports: the artifacts a program (or a multimodal agent) actually consumes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from image_annotate_mcp import export, store

ITEMS = [
    {"name": "出战按钮", "type": "box", "box": [40, 50, 100, 60]},
    {"name": "晶矿", "type": "point", "point": [160, 100]},
]


@pytest.fixture()
def saved(session):
    session.apply_save({"images": [{"id": "img1", "items": ITEMS}]})
    store.save_session(session)
    return session


def test_py_constants_exec_and_hold_the_right_numbers(saved):
    result = export.export("board_ui", fmt="py")
    namespace: dict = {}
    exec(compile(result["constants"], "<generated>", "exec"), namespace)  # noqa: S102

    assert namespace["BOARD_UI_IMG1_SIZE"] == (320, 200)
    assert namespace["BOARD_UI_IMG1_ITEM1"] == (40, 50, 100, 60)
    assert namespace["BOARD_UI_IMG1_ITEM2"] == (160, 100)
    assert namespace["BOARD_UI_TEMPLATES"]["img1"]["item1"].endswith(".png")
    # the Chinese names survive as comments, not as identifiers
    assert "出战按钮" in result["constants"]
    assert "出战按钮" not in result["constants"].split("\n")[0]


def test_py_file_on_disk_is_valid_python(saved, data_dir):
    result = export.export("board_ui", fmt="py")
    source = Path(result["files"][0]).read_text(encoding="utf-8")
    compile(source, result["files"][0], "exec")


def test_png_keeps_the_original_size(saved):
    result = export.export("board_ui", fmt="png")
    rendered = Image.open(result["files"][0])
    assert rendered.size == (320, 200)
    assert rendered.mode == "RGB"


def test_png_actually_marks_the_box(saved):
    path = export.export("board_ui", fmt="png")["files"][0]
    img = Image.open(path).convert("RGB")
    # the box outline sits exactly on x=40, y=50
    assert img.getpixel((40, 50))[0] > 150
    # a pixel far outside the box stays as the dark background
    assert img.getpixel((300, 20)) == (20, 30, 40)


def test_json_export_round_trips(saved):
    path = export.export("board_ui", fmt="json")["files"][0]
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    assert payload["schema"] == 2
    assert payload["images"][0]["items"][0]["box"] == [40, 50, 100, 60]


def test_yaml_export_is_readable_without_pyyaml(saved):
    path = export.export("board_ui", fmt="yaml")["files"][0]
    text = Path(path).read_text(encoding="utf-8")
    assert "schema: 2" in text
    assert "board_ui" in text
    assert "出战按钮" in text


def test_unknown_format_says_what_is_supported(saved):
    with pytest.raises(ValueError) as exc:
        export.export("board_ui", fmt="csv")
    assert "png" in str(exc.value)
    assert "yaml" in str(exc.value)


def test_export_still_works_when_the_original_file_is_gone(saved, sample_png):
    sample_png.unlink()
    path = export.export("board_ui", fmt="png")["files"][0]
    assert Image.open(path).size == (320, 200)


def test_missing_snapshot_says_what_to_do(saved, data_dir, sample_png):
    # both the snapshot and the original file are gone -> nothing to render on
    for snapshot in (data_dir / "sources").glob("*.png"):
        snapshot.unlink()
    sample_png.unlink()
    with pytest.raises(FileNotFoundError) as exc:
        export.export("board_ui", fmt="png")
    assert "annotate_export(fmt='json')" in str(exc.value)


POLY_ITEMS = [
    {"name": "技能环", "type": "polygon", "points": [[40, 50], [140, 50], [90, 110]]},
    {"name": "隐藏按钮", "type": "box", "box": [200, 20, 40, 20], "hidden": True},
]


def test_py_constants_emit_polygon_vertices(session):
    session.apply_save({"images": [{"id": "img1", "items": POLY_ITEMS}]})
    store.save_session(session)
    result = export.export("board_ui", fmt="py")
    namespace: dict = {}
    exec(compile(result["constants"], "<generated>", "exec"), namespace)  # noqa: S102

    assert namespace["BOARD_UI_IMG1_ITEM1"] == [(40, 50), (140, 50), (90, 110)]


def test_png_tints_the_polygon_and_skips_hidden_items(session):
    session.apply_save({"images": [{"id": "img1", "items": POLY_ITEMS}]})
    store.save_session(session)
    img = Image.open(export.export("board_ui", fmt="png")["files"][0]).convert("RGB")

    # the polygon's translucent fill tints the red button underneath it
    red, green, blue = img.getpixel((90, 70))
    assert green > 70, "polygon fill was not composited onto the screenshot"
    assert red < 200

    # the hidden box at (200,20) is left out of the picture entirely
    assert img.getpixel((200, 20)) == (20, 30, 40)
