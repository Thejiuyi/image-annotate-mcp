"""Protocol-level test: spawn the real server over stdio and talk JSON-RPC to it.

This is the only test that proves the transport is intact. Anything that writes to
stdout inside the server would corrupt the framing and show up here as a hang or a
parse error, which is exactly the failure mode the original prototype had.
"""

from __future__ import annotations

import json
import os
import sys

import anyio
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

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


_ITEMS = [
    {"name": "红块", "type": "box", "box": [40, 50, 100, 60]},
    {"name": "中心", "type": "point", "point": [160, 100]},
]


def _params(data_dir) -> StdioServerParameters:
    env = dict(os.environ)
    env["IMAGE_ANNOTATE_DATA_DIR"] = str(data_dir)
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "image_annotate_mcp", "--no-open", "--base-port", "8985"],
        env=env,
    )


def _save_over_http(url: str, image_block: dict) -> dict:
    """Pretend to be the browser: POST /save with one image's items."""
    import urllib.request

    base = url.rsplit("/?", 1)[0]
    body = json.dumps({"images": [image_block]}).encode("utf-8")
    request = urllib.request.Request(
        f"{base}/save", data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    # the machine-wide proxy env would hijack loopback otherwise
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=15) as response:
        return json.loads(response.read())


def _payload(result) -> dict:
    """Tools return dicts; the SDK may hand them back as structured or as JSON text."""
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict) and structured:
        # the SDK wraps plain dict returns in {"result": ...} on some versions
        if set(structured) == {"result"}:
            return structured["result"]
        return structured
    for block in result.content:
        text = getattr(block, "text", None)
        if text:
            return json.loads(text)
    raise AssertionError(f"工具没有返回可解析的内容：{result!r}")


async def _exercise(data_dir, sample_png) -> dict:
    out: dict = {}
    async with (
        stdio_client(_params(data_dir)) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()

        tools = await session.list_tools()
        out["tool_names"] = sorted(t.name for t in tools.tools)

        opened = _payload(
            await session.call_tool(
                "annotate_image",
                {"source": str(sample_png), "name": "proto", "open_browser": False},
            )
        )
        out["opened"] = opened

        status = _payload(
            await session.call_tool("annotate_status", {"session": opened["session"]})
        )
        out["status"] = status

        out["waited_pending"] = _payload(
            await session.call_tool(
                "annotate_wait", {"session": opened["session"], "timeout_s": 0.5}
            )
        )

        # pretend the human hit 保存, so the export / render tools have something to chew on
        _save_over_http(opened["url"], {"id": "img1", "items": _ITEMS})

        out["exported"] = _payload(
            await session.call_tool("annotate_export", {"name": "proto", "fmt": "py"})
        )

        rendered = await session.call_tool("annotate_render", {"name": "proto"})
        out["render_block_types"] = [getattr(b, "type", type(b).__name__) for b in rendered.content]
        out["render_bytes"] = sum(len(getattr(b, "data", b"")) for b in rendered.content)

        cancelled = _payload(
            await session.call_tool("annotate_cancel", {"session": opened["session"]})
        )
        out["cancelled"] = cancelled

        listing = _payload(await session.call_tool("annotate_list", {}))
        out["listing"] = listing
    return out


def test_stdio_transport_and_tool_round_trip(data_dir, sample_png):
    result = anyio.run(_exercise, data_dir, sample_png)

    assert set(result["tool_names"]) == EXPECTED_TOOLS

    opened = result["opened"]
    assert opened["ok"] is True
    assert opened["url"].startswith("http://127.0.0.1:")
    assert opened["images"][0]["size"] == [320, 200]

    assert result["status"]["status"] == "pending"
    # a blocking tool that times out must come back as a normal result, not an error
    assert result["waited_pending"]["status"] == "pending"
    assert "annotate_wait" in result["waited_pending"]["hint"]
    assert result["cancelled"]["ok"] is True
    assert result["listing"]["ok"] is True

    exported = result["exported"]
    assert exported["ok"] is True
    assert "PROTO_IMG1_ITEM1 = (40, 50, 100, 60)" in exported["constants"]

    # annotate_render must hand the agent actual image content, not a path
    assert "image" in result["render_block_types"], result["render_block_types"]
    assert result["render_bytes"] > 1000, "渲染出来的图片太小，可能没画上东西"


def test_unknown_tool_name_is_reported_as_an_error_result(data_dir):
    async def bad_call():
        async with (
            stdio_client(_params(data_dir)) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            return await session.call_tool("annotate_everything", {})

    result = anyio.run(bad_call)
    is_error = getattr(result, "isError", getattr(result, "is_error", None))
    assert is_error is True, f"未知工具应当返回 isError，实际 {result!r}"
    text = " ".join(getattr(b, "text", "") for b in result.content)
    assert "Unknown tool" in text or "annotate_everything" in text


def test_server_writes_nothing_to_stdout(data_dir, sample_png):
    """The child's stdout is the JSON-RPC stream; a stray print would break framing."""
    import subprocess

    proc = subprocess.run(
        [sys.executable, "-m", "image_annotate_mcp", "--version"],
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ, "IMAGE_ANNOTATE_DATA_DIR": str(data_dir)},
    )
    assert proc.returncode == 0
    assert proc.stdout.strip().startswith("annotate-mcp ")  # argparse --version only
    assert proc.stdout.count("\n") <= 1
