"""The local HTTP surface the browser page talks to.

Only three things matter here:

* ``GET  /``        -- the annotation page (single file, no CDN, works offline)
* ``GET  /frame``   -- current base image as JPEG + session metadata
* ``POST /save``    -- persist the annotations and wake the waiting agent

The server binds ``127.0.0.1`` only. One server per session, so two sessions can
never see each other's images.
"""

from __future__ import annotations

import base64
import contextlib
import io
import json
import os
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from PIL import Image

from . import store
from .sessions import Session

__all__ = ["make_server", "Handler"]

WEB_DIR = Path(__file__).with_name("web")
MAX_BODY = 32 * 1024 * 1024  # 32 MB is plenty for a page full of boxes


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    # On Windows SO_REUSEADDR lets a second process bind an already-used port,
    # which would silently break "port already taken -> try the next one".
    allow_reuse_address = os.name != "nt"
    session: Session


def make_server(session: Session, base_port: int, attempts: int = 20) -> tuple[_Server, int]:
    last: OSError | None = None
    for port in range(base_port, base_port + attempts):
        try:
            server = _Server(("127.0.0.1", port), Handler)
        except OSError as exc:
            last = exc
            continue
        server.session = session
        return server, port
    raise RuntimeError(
        f"端口 {base_port}–{base_port + attempts - 1} 全被占用（最后一个错误：{last!r}）。"
        "用 --base-port 换一段，或先关掉占着这些端口的进程。"
    )


def to_jpeg_bytes(img: Image.Image, quality: int = 92) -> bytes:
    if img.mode not in ("RGB", "L"):
        background = Image.new("RGB", img.size, (255, 255, 255))
        rgba = img.convert("RGBA")
        background.paste(rgba, mask=rgba.split()[-1])
        img = background
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


class Handler(BaseHTTPRequestHandler):
    server_version = "image-annotate-mcp"
    protocol_version = "HTTP/1.1"

    # -- plumbing -------------------------------------------------------

    def log_message(self, *args) -> None:  # noqa: D102 - silence, never pollute stdout
        pass

    @property
    def session(self) -> Session:
        return self.server.session  # type: ignore[attr-defined]

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        with contextlib.suppress(BrokenPipeError, ConnectionResetError):
            self.wfile.write(body)

    def _json(self, obj: dict, code: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self._send(code, body, "application/json; charset=utf-8")

    def _fail(self, code: int, message: str) -> None:
        self._json({"ok": False, "error": message}, code)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            raise ValueError("请求体是空的。")
        if length > MAX_BODY:
            raise ValueError(f"请求体太大（{length} 字节，上限 {MAX_BODY}）。")
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw or b"{}")
        except json.JSONDecodeError as exc:
            raise ValueError(f"请求体不是合法 JSON：{exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("请求体必须是 JSON 对象。")
        return data

    def _check_session(self, query: dict) -> bool:
        wanted = (query.get("s") or [None])[0]
        if wanted and wanted != self.session.id:
            self._fail(
                403,
                f"这个端口属于会话 {self.session.id}，不是 {wanted}。"
                "请用 annotate_image 返回的 url 打开。",
            )
            return False
        return True

    # -- GET ------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        if not self._check_session(query):
            return
        try:
            if parsed.path in ("/", "/index.html"):
                self._page()
            elif parsed.path == "/frame":
                self._frame(query)
            elif parsed.path == "/status":
                self._json({"ok": True, **self.session.status_dict()})
            elif parsed.path == "/healthz":
                self._json({"ok": True, "session": self.session.id})
            elif parsed.path == "/favicon.ico":
                self._send(204, b"", "image/x-icon")
            else:
                self._fail(404, f"没有这个路径：{parsed.path}")
        except Exception as exc:  # noqa: BLE001 - never kill the server thread
            _log(f"GET {parsed.path} 失败：{exc!r}")
            self._fail(500, f"{type(exc).__name__}: {exc}")

    def _page(self) -> None:
        html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
        self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")

    def _frame(self, query: dict) -> None:
        image_id = (query.get("img") or [None])[0]
        entry = self.session.get_image(image_id)
        if (query.get("fresh") or [None])[0] == "1" and entry.refreshable:
            entry = self.session.refresh_image(entry.id)
        jpeg = to_jpeg_bytes(entry.image)
        self._json(
            {
                "ok": True,
                "session": self.session.id,
                "name": self.session.name,
                "rev": self.session.rev,
                "status": self.session.status,
                "saved_at": self.session.saved_at,
                "jpeg": base64.b64encode(jpeg).decode("ascii"),
                "image": {
                    "id": entry.id,
                    "name": entry.name,
                    "size": entry.size,
                    "source": entry.source,
                    "refreshable": entry.refreshable,
                },
                "images": [
                    {
                        "id": e.id,
                        "name": e.name,
                        "size": e.size,
                        "refreshable": e.refreshable,
                        # Seed the page with whatever was already saved, so a
                        # refresh of the browser tab cannot silently wipe it.
                        "items": [dict(it) for it in self.session.items.get(e.id, [])],
                    }
                    for e in (self.session.images[i] for i in self.session.order)
                ],
            }
        )

    # -- POST -----------------------------------------------------------

    def do_POST(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        if not self._check_session(query):
            return
        try:
            if parsed.path == "/save":
                self._save()
            elif parsed.path == "/cancel":
                self._cancel()
            else:
                self._fail(404, f"没有这个路径：{parsed.path}")
        except ValueError as exc:
            self._fail(400, str(exc))
        except Exception as exc:  # noqa: BLE001
            _log(f"POST {parsed.path} 失败：{exc!r}")
            self._fail(500, f"{type(exc).__name__}: {exc}")

    def _save(self) -> None:
        payload = self._read_json()
        if payload.get("name"):
            self.session.name = str(payload["name"]).strip() or self.session.name
        # One atomic block: validate -> crop templates -> bump rev -> wake the agent.
        # Splitting these lets a waiter see items that have no template filenames yet.
        with self.session.atomic():
            result = self.session.apply_save(payload)
            try:
                written = store.save_session(self.session)
            except Exception as exc:  # noqa: BLE001 - keep the in-memory result usable
                _log(f"落盘失败：{exc!r}")
                written = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        self._json({**result, "written": written})

    def _cancel(self) -> None:
        self.session.cancel()
        self._json({"ok": True, "session": self.session.id, "status": "cancelled"})


def _log(message: str) -> None:
    """Log to stderr only -- stdout belongs to the MCP protocol."""
    print(f"[image-annotate-mcp] {message}", file=sys.stderr)
