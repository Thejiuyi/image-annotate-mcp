"""The MCP layer itself: are all eight tools registered, do they behave."""

from __future__ import annotations

import json
import urllib.request

import anyio
import pytest

from image_annotate_mcp import server as srv
from image_annotate_mcp import sessions as sessions_mod

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

EXPECTED_TOOLS = {
    "annotate_image",
    "annotate_wait",
    "annotate_status",
    "annotate_cancel",
    "annotate_list",
    "annotate_load",
    "annotate_export",
    "annotate_render",
}


@pytest.fixture(autouse=True)
def _isolated_manager(data_dir):
    sessions_mod.configure(base_port=8970, auto_open=False)
    yield
    sessions_mod.reset_manager()


def test_all_eight_tools_are_registered():
    tools = anyio.run(srv.mcp.list_tools)
    assert {tool.name for tool in tools} == EXPECTED_TOOLS


def test_annotate_image_schema_exposes_the_documented_arguments():
    tools = {tool.name: tool for tool in anyio.run(srv.mcp.list_tools)}
    schema = tools["annotate_image"].input_schema
    assert set(schema["properties"]) == {"source", "name", "open_browser", "resize_to"}
    assert "source" not in schema.get("required", [])


def test_wait_documents_that_pending_is_not_an_error():
    tools = {tool.name: tool for tool in anyio.run(srv.mcp.list_tools)}
    description = tools["annotate_wait"].description or ""
    assert "pending" in description
    assert "timeout" in description


def test_annotate_image_opens_a_session_without_a_browser(sample_png):
    result = srv.annotate_image(source=str(sample_png), name="t", open_browser=False)
    assert result["ok"] is True
    assert result["session"].startswith("s")
    assert result["url"].startswith("http://127.0.0.1:")
    assert result["images"][0]["size"] == [320, 200]
    assert "annotate_wait" in result["hint"]


def test_status_then_save_then_wait(sample_png):
    opened = srv.annotate_image(source=str(sample_png), open_browser=False)
    sid = opened["session"]

    status = srv.annotate_status(sid)
    assert status["status"] == "pending"
    assert status["items_count"] == 0

    base = opened["url"].rsplit("/?", 1)[0]
    body = json.dumps(
        {
            "name": "board_ui",
            "images": [
                {"id": "img1", "items": [{"name": "红块", "type": "box", "box": [40, 50, 10, 10]}]}
            ],
        }
    ).encode()
    req = urllib.request.Request(
        f"{base}/save", data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    with OPENER.open(req, timeout=10) as resp:
        assert json.loads(resp.read())["ok"] is True

    waited = srv.annotate_wait(sid, timeout_s=2)
    assert waited["status"] == "saved"
    assert waited["images"][0]["items"][0]["name"] == "红块"


def test_wait_on_a_dead_session_is_not_an_exception():
    result = srv.annotate_wait("s999", timeout_s=0.1)
    assert result["status"] == "unknown_session"
    assert "annotate_image" in result["error"]


def test_cancel_reports_open_sessions_when_the_id_is_wrong():
    result = srv.annotate_cancel("s999")
    assert result["ok"] is False
    assert "open_sessions" in result


def test_list_and_load_round_trip(sample_png):
    opened = srv.annotate_image(source=str(sample_png), open_browser=False)
    base = opened["url"].rsplit("/?", 1)[0]
    body = json.dumps(
        {"images": [{"id": "img1", "items": [{"name": "a", "type": "point", "point": [5, 6]}]}]}
    ).encode()
    req = urllib.request.Request(
        f"{base}/save", data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    with OPENER.open(req, timeout=10):
        pass

    listing = srv.annotate_list()
    assert listing["count"] == 1
    assert listing["items"][0]["items"] == 1

    loaded = srv.annotate_load("board_ui")
    assert loaded["ok"] is True
    assert loaded["annotation"]["images"][0]["items"][0]["point"] == [5, 6]


def test_export_returns_the_generated_source(sample_png):
    opened = srv.annotate_image(source=str(sample_png), open_browser=False)
    base = opened["url"].rsplit("/?", 1)[0]
    body = json.dumps(
        {"images": [{"id": "img1", "items": [{"name": "a", "type": "box", "box": [1, 2, 3, 4]}]}]}
    ).encode()
    req = urllib.request.Request(
        f"{base}/save", data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    with OPENER.open(req, timeout=10):
        pass

    result = srv.annotate_export("board_ui", fmt="py")
    assert result["ok"] is True
    assert "BOARD_UI_IMG1_A = (1, 2, 3, 4)" in result["constants"]


def test_export_of_a_missing_name_returns_ok_false_not_a_crash():
    result = srv.annotate_export("does-not-exist", fmt="py")
    assert result["ok"] is False
    assert "annotate_list" in result["error"]
