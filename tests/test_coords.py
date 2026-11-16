"""Coordinates are the whole product: a box must map to the exact pixels the user saw."""

from __future__ import annotations

from PIL import Image

from image_annotate_mcp import store
from image_annotate_mcp.sources import load_image


def _save_one(session, items):
    session.apply_save({"images": [{"id": "img1", "items": items}]})
    return store.save_session(session)


def test_box_crop_matches_the_pixels_under_it(session):
    # The red rectangle in the fixture spans (40,50)-(139,109).
    written = _save_one(
        session,
        [{"name": "红块", "type": "box", "box": [40, 50, 100, 60]}],
    )
    template = store.templates_dir() / written["templates"][0]
    crop = Image.open(template).convert("RGB")

    assert crop.size == (100, 60)
    assert crop.getpixel((0, 0)) == (200, 60, 70)
    assert crop.getpixel((99, 59)) == (200, 60, 70)


def test_point_is_stored_verbatim_in_original_pixels(session):
    _save_one(session, [{"name": "中心", "type": "point", "point": [160, 100]}])
    payload = store.load_annotation("board_ui")
    assert payload["images"][0]["items"][0]["point"] == [160, 100]
    assert payload["images"][0]["size"] == [320, 200]


def test_out_of_bounds_box_is_clamped_not_rejected(session):
    _save_one(session, [{"name": "越界", "type": "box", "box": [300, 180, 100, 100]}])
    payload = store.load_annotation("board_ui")
    item = payload["images"][0]["items"][0]
    x, y, w, h = item["box"]
    assert x == 300 and y == 180
    assert x + w <= 320 and y + h <= 200
    assert w >= 1 and h >= 1


def test_out_of_bounds_point_is_clamped(session):
    _save_one(session, [{"name": "远", "type": "point", "point": [9999, -5]}])
    item = store.load_annotation("board_ui")["images"][0]["items"][0]
    assert item["point"] == [319, 0]


def test_resize_to_reports_both_sizes(data_dir, sample_png):
    img, meta = load_image(str(sample_png), resize_to=[640, 400])
    assert img.size == (640, 400)
    assert meta["size_before"] == [320, 200]
    assert meta["size_after"] == [640, 400]
    assert meta.get("resized") is True


def test_without_resize_the_size_is_untouched(data_dir, sample_png):
    img, meta = load_image(str(sample_png))
    assert img.size == (320, 200)
    assert meta["size_before"] == meta["size_after"] == [320, 200]
    assert "resized" not in meta


def test_exif_rotation_is_applied_so_coordinates_match_what_is_seen(tmp_path):
    from PIL import Image as PILImage

    img = PILImage.new("RGB", (320, 200), (10, 20, 30))
    exif = img.getexif()
    exif[274] = 6  # orientation: rotate 90 CW on display
    path = tmp_path / "rotated.jpg"
    img.save(path, exif=exif)

    loaded, meta = load_image(str(path))
    assert loaded.size == (200, 320)
    assert meta["size_after"] == [200, 320]
