"""What actually lands on disk, and whether an old annotation can still be read."""

from __future__ import annotations

import json

import pytest
from PIL import Image

from image_annotate_mcp import store

ITEMS = [
    {"name": "出战按钮", "type": "box", "box": [40, 50, 100, 60]},
    {"name": "晶矿", "type": "point", "point": [160, 100]},
]


def _save(session, items=ITEMS):
    session.apply_save({"images": [{"id": "img1", "items": items}]})
    return store.save_session(session)


def test_writes_json_markdown_and_templates(session, data_dir):
    written = _save(session)

    json_path = data_dir / "annotations" / "board_ui.json"
    md_path = data_dir / "annotations" / "board_ui.md"
    assert json_path.is_file()
    assert md_path.is_file()
    assert len(written["templates"]) == 1

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["schema"] == 2
    assert payload["images"][0]["items"][0]["name"] == "出战按钮"
    assert payload["images"][0]["items"][0]["template"].endswith(".png")
    assert payload["images"][0]["snapshot"] == "board_ui__img1.png"

    markdown = md_path.read_text(encoding="utf-8")
    assert "出战按钮" in markdown
    assert "x 40 y 50 100×60" in markdown
    assert "(160, 100)" in markdown


def test_template_filename_is_ascii_but_the_name_is_not(session, data_dir):
    written = _save(session, [{"name": "出战按钮", "type": "box", "box": [40, 50, 10, 10]}])
    filename = written["templates"][0]

    assert filename.isascii()
    assert filename == "board_ui__img1__item1.png"
    payload = json.loads((data_dir / "annotations" / "board_ui.json").read_text(encoding="utf-8"))
    assert payload["images"][0]["items"][0]["name"] == "出战按钮"


def test_duplicate_names_do_not_overwrite_each_other(session, data_dir):
    written = _save(
        session,
        [
            {"name": "btn", "type": "box", "box": [0, 0, 10, 10]},
            {"name": "btn", "type": "box", "box": [20, 20, 10, 10]},
        ],
    )
    assert written["templates"] == [
        "board_ui__img1__btn.png",
        "board_ui__img1__btn_2.png",
    ]


def test_resaving_overwrites_the_same_file(session, data_dir):
    _save(session, [ITEMS[0]])
    _save(session, ITEMS)
    payload = store.load_annotation("board_ui")
    assert len(payload["images"][0]["items"]) == 2
    assert len(list((data_dir / "annotations").glob("*.json"))) == 1


def test_v1_payload_is_read_but_not_rewritten(session, data_dir):
    legacy = {
        "name": "legacy_ui",
        "image": "游戏实时画面",
        "size": [1920, 1080],
        "saved_at": "2026-11-15 16:15:20",
        "items": [
            {"index": 1, "name": "晶矿", "type": "point", "point": [1614, 398], "note": ""},
            {
                "index": 2,
                "name": "出战按钮",
                "type": "box",
                "box": [1671, 713, 240, 70],
                "note": "",
                "template": "features/ui__item2.png",
            },
        ],
    }
    ann_dir = data_dir / "annotations"
    ann_dir.mkdir(parents=True, exist_ok=True)
    path = ann_dir / "legacy_ui.json"
    original = json.dumps(legacy, ensure_ascii=False, indent=1)
    path.write_text(original, encoding="utf-8")

    payload = store.load_annotation("legacy_ui")
    assert payload["schema"] == 2
    assert payload["upcast_from"] == 1
    assert payload["images"][0]["size"] == [1920, 1080]
    assert payload["images"][0]["items"][1]["box"] == [1671, 713, 240, 70]
    assert path.read_text(encoding="utf-8") == original, "v1 file must stay untouched"


def test_list_reports_counts_newest_first(session, data_dir):
    _save(session)
    rows = store.list_annotations()
    assert len(rows) == 1
    assert rows[0]["name"] == "board_ui"
    assert rows[0]["items"] == 2
    assert rows[0]["images"] == 1


def test_missing_annotation_names_what_does_exist(session, data_dir):
    _save(session)
    with pytest.raises(FileNotFoundError) as exc:
        store.load_annotation("nope")
    message = str(exc.value)
    assert "board_ui" in message
    assert "annotate_list" in message


def test_lookup_by_display_name_works(session, data_dir):
    session.name = "主界面 UI"
    _save(session)
    payload = store.load_annotation("主界面 UI")
    assert payload["name"] == "主界面 UI"


TRIANGLE = [[40, 50], [140, 50], [90, 110]]


def test_polygon_template_is_masked_to_the_outline(session, data_dir):
    written = _save(session, [{"name": "技能环", "type": "polygon", "points": TRIANGLE}])
    template = Image.open(data_dir / "templates" / written["templates"][0])

    assert template.mode == "RGBA"
    assert template.size == (100, 60), "template should be the vertex bbox, not the screenshot"
    # inside the triangle the screenshot survives untouched
    assert template.getpixel((50, 10)) == (200, 60, 70, 255)
    # the bbox corner the user did not enclose is cut away, not left opaque
    assert template.getpixel((99, 59))[3] == 0


def test_polygon_row_in_markdown_carries_the_bbox(session, data_dir):
    _save(session, [{"name": "技能环", "type": "polygon", "points": TRIANGLE}])
    markdown = (data_dir / "annotations" / "board_ui.md").read_text(encoding="utf-8")

    assert "多边形" in markdown
    assert "3 点 · bbox x 40 y 50 100×60" in markdown


def test_hidden_items_still_get_a_template(session, data_dir):
    written = _save(
        session,
        [{"name": "隐藏按钮", "type": "box", "box": [40, 50, 10, 10], "hidden": True}],
    )

    assert len(written["templates"]) == 1
    payload = store.load_annotation("board_ui")
    assert payload["images"][0]["items"][0]["hidden"] is True
    markdown = (data_dir / "annotations" / "board_ui.md").read_text(encoding="utf-8")
    assert "隐藏" in markdown
