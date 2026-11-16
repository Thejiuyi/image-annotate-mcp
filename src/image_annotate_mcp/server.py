"""The MCP tool surface.

Eight tools, one job each:

===========================  ==========================================================
``annotate_image``           open a session, hand back a localhost URL
``annotate_wait``            **block** until the human hits 保存 (or timeout)
``annotate_status``          non-blocking peek, for "is the user still drawing?"
``annotate_cancel``          close a session, wake up anyone waiting
``annotate_list``            what annotations already exist on disk
``annotate_load``            read one back, full structured payload
``annotate_export``          png / py / json / yaml artifacts
``annotate_render``          the numbered picture itself, as image content
===========================  ==========================================================

Everything logs to stderr; stdout belongs to the JSON-RPC transport.
"""

from __future__ import annotations

import sys

from mcp.server.mcpserver import Image as MCPImage
from mcp.server.mcpserver import MCPServer

from . import export as export_mod
from . import store
from .sessions import SessionError, get_manager

__all__ = ["mcp", "main"]

mcp = MCPServer(
    "image-annotate-mcp",
    title="Image Annotate MCP",
    version="0.3.0",
    instructions=(
        "Human-in-the-loop image annotation. Open a session with annotate_image, "
        "the user draws boxes / points / polygons in a local web page, then "
        "annotate_wait blocks "
        "until they hit save and returns pixel coordinates, names and cropped "
        "templates. annotate_wait blocking for a while is normal, not a hang."
    ),
)


def _fail(exc: Exception) -> RuntimeError:
    return RuntimeError(f"{exc}")


@mcp.tool(
    description=(
        "Open an annotation session for one or more images and return a localhost URL. "
        "The user opens that URL and draws boxes (templates), points (click targets) "
        "or free-form polygons joined by straight segments, "
        "names them, then hits 保存. Then call annotate_wait to collect the result.\n\n"
        "source: local file path | data URL | raw base64 | 'screen' (live screen capture) "
        "| a list of any of those for a multi-image session. Omit it to capture the screen.\n"
        "resize_to: optional [width, height]; by default the image is NOT resampled, so "
        "coordinates always match the original file."
    )
)
def annotate_image(
    source: str | list[str] | None = None,
    name: str | None = None,
    open_browser: bool = True,
    resize_to: list[int] | None = None,
) -> dict:
    manager = get_manager()
    manager.auto_open = bool(open_browser)
    try:
        session = manager.create(name=name, sources=source, resize_to=resize_to)
    except SessionError as exc:
        raise _fail(exc) from exc
    except Exception as exc:  # noqa: BLE001 - surface the real reason to the agent
        raise RuntimeError(f"{type(exc).__name__}: {exc}") from exc

    return {
        "ok": True,
        "session": session.id,
        "url": session.url,
        "name": session.name,
        "rev": session.rev,
        "images": [
            {
                "id": session.images[i].id,
                "name": session.images[i].name,
                "size": session.images[i].size,
                "source": session.images[i].source,
            }
            for i in session.order
        ],
        "data_dir": str(store.data_dir()),
        "hint": (
            f"让用户在浏览器打开 {session.url} 框选，然后点「保存」；"
            f"之后调用 annotate_wait(session='{session.id}') 取结果。"
        ),
    }


@mcp.tool(
    description=(
        "Block until the user saves the annotation (or the timeout fires), then return "
        "the annotations: per image, a list of "
        "{index, name, type, box|point|points, template, hidden?}.\n\n"
        "A status of 'pending' means the user has not saved yet -- that is NOT an error, "
        "just call annotate_wait again. Pass since_rev to only wait for saves newer than "
        "what you already have. Keep timeout_s below your MCP client's own tool timeout."
    )
)
def annotate_wait(session: str, timeout_s: float = 240.0, since_rev: int = 0) -> dict:
    try:
        sess = get_manager().get(session)
    except SessionError as exc:
        return {"status": "unknown_session", "session": session, "error": str(exc)}
    result = sess.wait(since_rev=since_rev, timeout_s=timeout_s)
    result["ok"] = True
    return result


@mcp.tool(
    description=(
        "Non-blocking status of one session: pending / saved / cancelled, current rev, "
        "how many items so far, and how long it has been open."
    )
)
def annotate_status(session: str) -> dict:
    try:
        return {"ok": True, **get_manager().get(session).status_dict()}
    except SessionError as exc:
        return {"ok": False, "status": "unknown_session", "error": str(exc)}


@mcp.tool(
    description="Close a session and its local web server. Anyone blocked in annotate_wait wakes up as cancelled."
)
def annotate_cancel(session: str) -> dict:
    closed = get_manager().cancel(session)
    if not closed:
        return {
            "ok": False,
            "error": f"没有会话 {session!r}；可能已经关掉了。",
            "open_sessions": [s["session"] for s in get_manager().list_sessions()],
        }
    return {"ok": True, "session": session, "status": "cancelled"}


@mcp.tool(description="List annotations saved on disk, newest first.")
def annotate_list(limit: int = 20) -> dict:
    rows = store.list_annotations(limit=limit)
    return {"ok": True, "dir": str(store.annotations_dir()), "count": len(rows), "items": rows}


@mcp.tool(
    description=(
        "Load one saved annotation by name (or file path) and return the full structured "
        "payload: schema 2 with images[] -> items[] and template filenames."
    )
)
def annotate_load(name: str) -> dict:
    try:
        payload = store.load_annotation(name)
    except FileNotFoundError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "annotation": payload}


@mcp.tool(
    description=(
        "Export a saved annotation. fmt='png' renders the base image with numbered "
        "outlines (for a multimodal agent to look at), 'py' emits coordinate constants "
        "plus a template map, 'json' / 'yaml' dump the payload. Returns file paths and, "
        "for 'py', the generated source."
    )
)
def annotate_export(
    name: str,
    fmt: str = "png",
    out_dir: str | None = None,
    image_id: str | None = None,
) -> dict:
    try:
        return export_mod.export(name, fmt=fmt, out_dir=out_dir, image_id=image_id)
    except (FileNotFoundError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}


@mcp.tool(
    description=(
        "Render the numbered annotation picture for one saved annotation and return it as "
        "image content, so you can read the labels yourself instead of asking the user to "
        "type names. Needs annotate_export(fmt='png') to have been run first, or it will "
        "render on the fly."
    )
)
def annotate_render(name: str, image_id: str | None = None) -> MCPImage:
    payload = store.load_annotation(name)
    path = export_mod.render_annotated(payload, image_id=image_id)
    return MCPImage(path=str(path))


def main(argv: list[str] | None = None) -> int:
    from .__main__ import main as cli_main

    return cli_main(argv)


def _log(message: str) -> None:
    print(f"[image-annotate-mcp] {message}", file=sys.stderr)
