"""End-to-end over real HTTP: the page's three calls, no browser needed.

The proxy handler is deliberately emptied -- this machine has HTTP_PROXY pointed at
a local process, and without bypassing it a request to 127.0.0.1 gets hijacked.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _get(url: str) -> tuple[int, bytes, str]:
    with OPENER.open(url, timeout=10) as resp:
        return resp.status, resp.read(), resp.headers.get("Content-Type", "")


def _post(url: str, payload: dict) -> tuple[int, dict]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with OPENER.open(req, timeout=10) as resp:
        return resp.status, json.loads(resp.read())


def _get_json(url: str) -> dict:
    _, body, _ = _get(url)
    return json.loads(body)


def test_page_is_served_and_offline_safe(session):
    status, body, ctype = _get(session.url)
    html = body.decode("utf-8")
    assert status == 200
    assert "text/html" in ctype
    assert "标注" in html
    # no CDN, no external fonts, no external scripts: the page must work offline
    assert "http://" not in html
    assert "https://" not in html
    assert "<script src" not in html
    assert "@import" not in html


def test_frame_returns_a_jpeg_and_the_session_shape(session):
    payload = _get_json(session.url.replace("/?s=", "/frame?s="))
    assert payload["ok"] is True
    assert payload["session"] == session.id
    assert payload["image"]["size"] == [320, 200]
    assert payload["jpeg"]
    assert payload["images"][0]["id"] == "img1"
    assert payload["images"][0]["items"] == []


def test_save_writes_files_and_wakes_the_agent(session, data_dir):
    base = session.url.rsplit("/?", 1)[0]
    status, result = _post(
        f"{base}/save",
        {
            "name": "board_ui",
            "images": [
                {
                    "id": "img1",
                    "items": [{"name": "红块", "type": "box", "box": [40, 50, 100, 60]}],
                }
            ],
        },
    )
    assert status == 200
    assert result["ok"] is True
    assert result["rev"] == 1
    assert result["total_items"] == 1
    assert result["written"]["templates"]

    assert (data_dir / "annotations" / "board_ui.json").is_file()
    waited = session.wait(since_rev=0, timeout_s=1)
    assert waited["status"] == "saved"
    # one call must be enough: the agent should not have to load the file again
    assert waited["images"][0]["items"][0]["template"].endswith(".png")


def test_reopening_the_page_shows_what_was_already_saved(session):
    base = session.url.rsplit("/?", 1)[0]
    _post(
        f"{base}/save",
        {"images": [{"id": "img1", "items": [{"name": "a", "type": "point", "point": [1, 2]}]}]},
    )
    payload = _get_json(f"{base}/frame?s={session.id}")
    assert payload["images"][0]["items"][0]["name"] == "a"
    assert payload["status"] == "saved"
    assert payload["rev"] == 1


def test_wrong_session_id_is_refused(session):
    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(session.url.replace(f"s={session.id}", "s=s999"))
    assert exc.value.code == 403
    assert "annotate_image" in exc.value.read().decode("utf-8")


def test_unknown_path_is_a_clean_404(session):
    base = session.url.rsplit("/?", 1)[0]
    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(f"{base}/nope")
    assert exc.value.code == 404


def test_bad_payload_is_a_400_with_a_usable_message(session):
    base = session.url.rsplit("/?", 1)[0]
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(f"{base}/save", {"images": [{"id": "img1", "items": [{"type": "circle"}]}]})
    assert exc.value.code == 400
    assert "circle" in exc.value.read().decode("utf-8")


def test_wait_never_sees_items_without_templates(session, monkeypatch):
    """Regression: apply_save used to notify before the crops were written, so a
    fast waiter got items with no template filename. Widen that window on purpose."""
    import threading
    import time

    from image_annotate_mcp import store as store_mod

    real = store_mod.save_session

    def slow(sess):
        time.sleep(0.4)
        return real(sess)

    monkeypatch.setattr(store_mod, "save_session", slow)

    base = session.url.rsplit("/?", 1)[0]
    payload = {
        "images": [
            {"id": "img1", "items": [{"name": "红块", "type": "box", "box": [40, 50, 10, 10]}]}
        ]
    }
    poster = threading.Thread(target=lambda: _post(f"{base}/save", payload), daemon=True)
    poster.start()

    started = time.monotonic()
    result = session.wait(since_rev=0, timeout_s=10)
    elapsed = time.monotonic() - started
    poster.join(timeout=5)

    boxes = [it for it in result["images"][0]["items"] if it["type"] == "box"]
    assert boxes, "框选没存下来"
    assert all("template" in it for it in boxes), "agent 拿到的框选缺模板文件名"
    assert elapsed >= 0.35, f"wait 只等了 {elapsed:.2f}s，说明它在落盘完成前就醒了"


def test_cancel_endpoint_closes_the_session(session):
    base = session.url.rsplit("/?", 1)[0]
    status, result = _post(f"{base}/cancel", {})
    assert status == 200
    assert result["status"] == "cancelled"
    assert session.wait(since_rev=0, timeout_s=1)["status"] == "cancelled"


def test_status_endpoint_matches_the_session(session):
    base = session.url.rsplit("/?", 1)[0]
    payload = _get_json(f"{base}/status?s={session.id}")
    assert payload["ok"] is True
    assert payload["session"] == session.id
    assert payload["status"] == "pending"
