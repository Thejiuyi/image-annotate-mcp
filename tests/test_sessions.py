"""The blocking handshake and its failure modes."""

from __future__ import annotations

import threading
import time

import pytest

from image_annotate_mcp.sessions import SessionError, _clean_items

POINT = {"name": "晶矿", "type": "point", "point": [10, 20]}


def test_snapshot_shape(session):
    snap = session.snapshot()
    assert snap["schema"] == 2
    assert snap["session"] == session.id
    assert snap["rev"] == 0
    assert snap["status"] == "pending"
    assert snap["images"][0]["id"] == "img1"
    assert snap["images"][0]["size"] == [320, 200]
    assert snap["images"][0]["items"] == []


def test_rev_increments_and_items_land(session):
    session.apply_save({"images": [{"id": "img1", "items": [POINT]}]})
    first = session.snapshot()
    session.apply_save({"images": [{"id": "img1", "items": [POINT, POINT]}]})
    second = session.snapshot()

    assert first["rev"] == 1
    assert second["rev"] == 2
    assert len(second["images"][0]["items"]) == 2
    assert second["status"] == "saved"
    assert second["saved_at"]


def test_wait_returns_immediately_when_already_saved(session):
    session.apply_save({"images": [{"id": "img1", "items": [POINT]}]})
    started = time.monotonic()
    result = session.wait(since_rev=0, timeout_s=5)
    assert result["status"] == "saved"
    assert time.monotonic() - started < 1.0
    assert result["images"][0]["items"][0]["name"] == "晶矿"


def test_wait_blocks_until_the_user_saves(session):
    box: dict = {}

    def waiter():
        box.update(session.wait(since_rev=0, timeout_s=5))

    thread = threading.Thread(target=waiter, daemon=True)
    thread.start()
    time.sleep(0.15)
    assert thread.is_alive(), "wait() returned before the user saved anything"

    session.apply_save({"images": [{"id": "img1", "items": [POINT]}]})
    thread.join(timeout=3)

    assert not thread.is_alive()
    assert box["status"] == "saved"
    assert box["rev"] == 1


def test_since_rev_ignores_older_saves(session):
    session.apply_save({"images": [{"id": "img1", "items": [POINT]}]})
    started = time.monotonic()
    result = session.wait(since_rev=1, timeout_s=0.2)
    elapsed = time.monotonic() - started

    assert result["status"] == "pending"
    assert result["rev"] == 1
    # it must actually block: returning instantly would turn the agent into a busy loop
    assert elapsed >= 0.15, (
        f"wait() returned after {elapsed:.3f}s instead of waiting for a new save"
    )


def test_timeout_reports_pending_and_tells_the_agent_what_to_do(session):
    started = time.monotonic()
    result = session.wait(since_rev=0, timeout_s=0.2)
    elapsed = time.monotonic() - started

    assert result["status"] == "pending"
    assert 0.15 <= elapsed < 3
    assert "annotate_wait" in result["hint"]
    assert result["elapsed_s"] >= 0


def test_cancel_wakes_a_waiting_agent(session):
    box: dict = {}
    thread = threading.Thread(
        target=lambda: box.update(session.wait(since_rev=0, timeout_s=10)), daemon=True
    )
    thread.start()
    time.sleep(0.1)
    session.cancel()
    thread.join(timeout=3)

    assert not thread.is_alive(), "cancel() did not wake the waiter"
    assert box["status"] == "cancelled"


def test_unknown_session_lists_what_is_alive(manager, session):
    with pytest.raises(SessionError) as exc:
        manager.get("nope")
    message = str(exc.value)
    assert "nope" in message
    assert session.id in message
    assert "annotate_image" in message


def test_unknown_image_id_is_rejected_with_the_valid_ids(session):
    with pytest.raises(ValueError) as exc:
        session.apply_save({"images": [{"id": "img9", "items": []}]})
    assert "img9" in str(exc.value)
    assert "img1" in str(exc.value)


def test_bad_item_type_is_rejected(session):
    with pytest.raises(ValueError) as exc:
        session.apply_save({"images": [{"id": "img1", "items": [{"type": "circle"}]}]})
    message = str(exc.value)
    assert "circle" in message
    # the refusal has to list what IS accepted, or the agent just retries
    assert "polygon" in message and "box" in message


def test_single_image_shorthand_is_accepted(session):
    session.apply_save({"items": [POINT]})
    assert session.snapshot()["images"][0]["items"][0]["name"] == "晶矿"


def test_clean_items_renumbers_and_clamps():
    items, clamped = _clean_items(
        [
            {"name": "a", "type": "point", "point": [5, 5]},
            {"name": "", "type": "box", "box": [-5, -5, 50, 50]},
        ],
        width=320,
        height=200,
    )
    assert [it["index"] for it in items] == [1, 2]
    assert items[1]["name"] == "item2"
    assert items[1]["box"][:2] == [0, 0]
    assert clamped == 1


POLY = {"name": "技能环", "type": "polygon", "points": [[10, 10], [60, 10], [60, 40], [10, 40]]}


def test_polygon_vertices_and_bbox_survive_a_save(session):
    session.apply_save({"images": [{"id": "img1", "items": [POLY]}]})
    item = session.snapshot()["images"][0]["items"][0]

    assert item["type"] == "polygon"
    assert item["points"] == [[10, 10], [60, 10], [60, 40], [10, 40]]
    assert item["bbox"] == [10, 10, 50, 30]


def test_polygon_needs_at_least_three_vertices(session):
    with pytest.raises(ValueError) as exc:
        session.apply_save(
            {"images": [{"id": "img1", "items": [{"type": "polygon", "points": [[1, 1], [5, 5]]}]}]}
        )
    message = str(exc.value)
    assert "points" in message
    assert "3" in message


def test_polygon_vertices_are_clamped_into_the_image():
    items, clamped = _clean_items(
        [{"name": "p", "type": "polygon", "points": [[-20, -20], [400, 10], [10, 400]]}],
        width=320,
        height=200,
    )
    assert items[0]["points"] == [[0, 0], [319, 10], [10, 199]]
    assert clamped == 1


def test_flat_polygon_is_refused_instead_of_saving_a_blank_template(session):
    with pytest.raises(ValueError) as exc:
        session.apply_save(
            {
                "images": [
                    {
                        "id": "img1",
                        "items": [{"type": "polygon", "points": [[10, 10], [50, 10], [90, 10]]}],
                    }
                ]
            }
        )
    message = str(exc.value)
    assert "面积是 0" in message
    # a refusal with no next action just makes the agent retry the same thing
    assert "框选" in message


def test_hidden_items_are_kept_not_dropped(session):
    session.apply_save({"images": [{"id": "img1", "items": [POINT, dict(POLY, hidden=True)]}]})
    items = session.snapshot()["images"][0]["items"]

    assert len(items) == 2
    assert "hidden" not in items[0]
    assert items[1]["hidden"] is True


def test_item_field_order_stays_readable():
    """The JSON is diffed by humans; key order is the contract, not an accident."""
    items, _ = _clean_items(
        [
            {"name": "a", "type": "box", "box": [1, 1, 2, 2]},
            {"name": "b", "type": "polygon", "points": [[0, 0], [9, 0], [9, 9]], "hidden": True},
        ],
        width=320,
        height=200,
    )
    assert list(items[0]) == ["index", "name", "type", "box", "note"]
    assert list(items[1]) == ["index", "name", "type", "points", "bbox", "note", "hidden"]
