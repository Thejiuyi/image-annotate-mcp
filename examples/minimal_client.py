"""Minimal end-to-end example: open a session, wait for the human, export constants.

    python examples/minimal_client.py                 # annotate the live screen
    python examples/minimal_client.py shot.png        # annotate an existing image

Needs the package installed (``pip install -e .`` in a checkout). It talks to the
server over stdio exactly the way a real MCP client does, so it also doubles as a
smoke test of the transport.
"""

from __future__ import annotations

import json
import sys

import anyio
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


def payload(result) -> dict:
    """Tools return dicts; the SDK may give them back as structured content or JSON text."""
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict) and structured:
        if set(structured) == {"result"}:
            return structured["result"]
        return structured
    for block in result.content:
        text = getattr(block, "text", None)
        if text:
            return json.loads(text)
    raise RuntimeError(f"工具没有返回可解析的内容：{result!r}")


async def run(source: str) -> int:
    # A real client config would say "command": "annotate-mcp" (the console script).
    # Running through the current interpreter keeps this example working from a venv
    # whose Scripts/ directory is not on PATH.
    params = StdioServerParameters(command=sys.executable, args=["-m", "image_annotate_mcp"])
    async with (
        stdio_client(params) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()

        opened = payload(
            await session.call_tool("annotate_image", {"source": source, "name": "demo"})
        )
        print(f"会话 {opened['session']}，在浏览器打开：{opened['url']}")
        print("（框选完点「保存」，这个脚本会自动收到结果）\n")

        rev = 0
        while True:
            waited = payload(
                await session.call_tool(
                    "annotate_wait",
                    {"session": opened["session"], "timeout_s": 240, "since_rev": rev},
                )
            )
            if waited["status"] == "saved":
                break
            if waited["status"] != "pending":
                print(f"结束：{waited['status']} —— {waited.get('hint', '')}")
                return 1
            print(f"还在等：{waited['hint']}", flush=True)
            rev = waited["rev"]

        for image in waited["images"]:
            print(f"[{image['id']}] {image['name']}  {image['size'][0]}×{image['size'][1]}")
            for item in image["items"]:
                coord = item.get("box") or item.get("point")
                print(f"    {item['index']}. {item['name']:<12} {item['type']:<6} {coord}")
                if item.get("template"):
                    print(f"       模板 → {item['template']}")

        exported = payload(
            await session.call_tool("annotate_export", {"name": "demo", "fmt": "py"})
        )
        print("\n生成的常量：\n")
        print(exported.get("constants") or exported)

        await session.call_tool("annotate_cancel", {"session": opened["session"]})
    return 0


def main() -> int:
    # line-buffer stdout: the session URL is the whole point of this script and must
    # appear immediately, not whenever the process happens to exit
    sys.stdout.reconfigure(line_buffering=True)
    source = sys.argv[1] if len(sys.argv) > 1 else "screen"
    return anyio.run(run, source)


if __name__ == "__main__":
    raise SystemExit(main())
