"""Session bookkeeping: one session == one browser page == one local HTTP server.

The whole point of this module is the blocking handshake:

    agent thread ──wait()──▶ Condition.wait_for(rev > since_rev)
                                     ▲
    browser POST /save ──apply_save()┘ rev += 1, notify_all()

No folder polling, no sleeps, no busy loops.
"""

from __future__ import annotations

import contextlib
import threading
import time
import webbrowser
from dataclasses import dataclass, field

from PIL import Image

from .sources import load_image

__all__ = [
    "SessionError",
    "ImageEntry",
    "Session",
    "SessionManager",
    "get_manager",
    "reset_manager",
    "configure",
    "polygon_area",
    "polygon_bbox",
]


class SessionError(RuntimeError):
    """Unknown / closed session. Message always says which sessions do exist."""


@dataclass
class ImageEntry:
    id: str
    name: str
    image: Image.Image
    source: str
    refreshable: bool = False
    meta: dict = field(default_factory=dict)

    @property
    def size(self) -> list[int]:
        return [int(self.image.width), int(self.image.height)]


def _clean_points(raw: object, index: int, width: int, height: int) -> tuple[list[list[int]], bool]:
    """Validate one polygon's vertices, clamping each into the image."""
    if not isinstance(raw, (list, tuple)) or len(raw) < 3:
        raise ValueError(f"第 {index} 项是多边形，points 需要至少 3 个 [x, y] 顶点，收到 {raw!r}。")
    pts: list[list[int]] = []
    moved = False
    for k, point in enumerate(raw, 1):
        try:
            vx, vy = (int(round(float(v))) for v in point)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"第 {index} 项的第 {k} 个顶点不是 [x, y] 两个数：{point!r}。"
            ) from exc
        cx = min(max(0, vx), max(0, width - 1))
        cy = min(max(0, vy), max(0, height - 1))
        if (cx, cy) != (vx, vy):
            moved = True
        pts.append([cx, cy])
    return pts, moved


def polygon_area(points: list[list[int]]) -> float:
    """Shoelace area, absolute. Used to reject degenerate outlines."""
    total = 0.0
    for i, (x1, y1) in enumerate(points):
        x2, y2 = points[(i + 1) % len(points)]
        total += float(x1) * float(y2) - float(x2) * float(y1)
    return abs(total) / 2.0


def polygon_bbox(points: list[list[int]]) -> list[int]:
    """``[x, y, w, h]`` around the vertices, same shape as a box."""
    xs = [int(p[0]) for p in points]
    ys = [int(p[1]) for p in points]
    x0, y0 = min(xs), min(ys)
    return [x0, y0, max(1, max(xs) - x0), max(1, max(ys) - y0)]


def _clean_items(raw: list, width: int, height: int) -> tuple[list[dict], int]:
    """Validate + clamp one image's items. Returns (items, clamped_count)."""
    if not isinstance(raw, list):
        raise ValueError("items 必须是数组。")
    out: list[dict] = []
    clamped = 0
    for i, it in enumerate(raw, 1):
        if not isinstance(it, dict):
            raise ValueError(f"第 {i} 项不是对象，收到 {type(it).__name__}。")
        kind = it.get("type")
        name = str(it.get("name") or f"item{i}").strip() or f"item{i}"
        note = str(it.get("note") or "")
        # Key order matters: it is what a human diffs when comparing two
        # annotations. Keep it index, name, type, <geometry>, note, hidden.
        rec: dict = {"index": len(out) + 1, "name": name, "type": kind}

        if kind == "box":
            try:
                x, y, bw, bh = (int(round(float(v))) for v in it["box"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(
                    f"第 {i} 项是框选，但 box 不是 [x, y, w, h] 四个数：{it.get('box')!r}。"
                ) from exc
            nx = min(max(0, x), max(0, width - 1))
            ny = min(max(0, y), max(0, height - 1))
            nw = min(max(1, bw), width - nx)
            nh = min(max(1, bh), height - ny)
            if (nx, ny, nw, nh) != (x, y, bw, bh):
                clamped += 1
            rec["box"] = [nx, ny, nw, nh]

        elif kind == "point":
            try:
                px, py = (int(round(float(v))) for v in it["point"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(
                    f"第 {i} 项是点选，但 point 不是 [x, y] 两个数：{it.get('point')!r}。"
                ) from exc
            cx = min(max(0, px), max(0, width - 1))
            cy = min(max(0, py), max(0, height - 1))
            if (cx, cy) != (px, py):
                clamped += 1
            rec["point"] = [cx, cy]

        elif kind == "polygon":
            pts, moved = _clean_points(it.get("points"), i, width, height)
            if moved:
                clamped += 1
            # A zero-area outline crops to a fully transparent PNG: the user thinks
            # it saved, the agent gets a template it cannot see. Fail loudly instead.
            if polygon_area(pts) < 1.0:
                raise ValueError(
                    f"第 {i} 项多边形围出来的面积是 0（顶点都在同一条线上？）。"
                    "请在界面上重新点几个点，或者改用框选。"
                )
            rec.update({"points": pts, "bbox": polygon_bbox(pts)})

        else:
            raise ValueError(
                f"第 {i} 项的 type 只能是 'box'、'point' 或 'polygon'，收到 {kind!r}。"
            )

        rec["note"] = note
        if it.get("hidden"):
            # Hiding is a view preference, not a delete: the item keeps its template
            # and still shows up in the table, the page just stops drawing it.
            rec["hidden"] = True
        out.append(rec)
    return out, clamped


class Session:
    """One annotation session, backed by one local HTTP server."""

    def __init__(self, sid: str, name: str) -> None:
        self.id = sid
        self.name = name
        self.images: dict[str, ImageEntry] = {}
        self.order: list[str] = []
        self.items: dict[str, list[dict]] = {}
        self.rev = 0
        self.saved_at: str | None = None
        self.status = "pending"  # pending | saved | cancelled
        self.created = time.time()
        self.url: str | None = None
        self.port: int | None = None
        self.httpd = None
        self._http_thread: threading.Thread | None = None
        self._cond = threading.Condition()

    # -- images ---------------------------------------------------------

    def add_image(self, img: Image.Image, meta: dict) -> str:
        iid = f"img{len(self.order) + 1}"
        self.images[iid] = ImageEntry(
            id=iid,
            name=str(meta.get("name") or iid),
            image=img,
            source=str(meta.get("source") or ""),
            refreshable=bool(meta.get("refreshable")),
            meta=dict(meta),
        )
        self.order.append(iid)
        self.items.setdefault(iid, [])
        return iid

    @property
    def primary(self) -> ImageEntry:
        return self.images[self.order[0]]

    def get_image(self, image_id: str | None = None) -> ImageEntry:
        if image_id is None:
            return self.primary
        if image_id not in self.images:
            raise SessionError(f"会话 {self.id} 里没有图片 {image_id!r}；可用的是 {self.order}。")
        return self.images[image_id]

    def refresh_image(self, image_id: str) -> ImageEntry:
        """Re-grab a refreshable (screen) image in place, keeping its items."""
        entry = self.get_image(image_id)
        if not entry.refreshable:
            return entry
        img, meta = load_image(entry.source)
        with self._cond:
            entry.image = img
            entry.meta.update(meta)
        return entry

    @contextlib.contextmanager
    def atomic(self):
        """Hold the session lock across a whole save.

        ``apply_save`` notifies waiters while still holding the lock, but a waiter
        can only re-acquire it once the *outer* ``with`` exits. Wrapping
        "validate + persist" in this block is what guarantees an agent never sees
        items without their template filenames.
        """
        with self._cond:
            yield

    def set_items(self, image_id: str, items: list[dict]) -> None:
        """Replace one image's items (used by store after it attaches template names)."""
        with self._cond:
            self.items[image_id] = items

    # -- state ----------------------------------------------------------

    def snapshot(self) -> dict:
        with self._cond:
            return {
                "schema": 2,
                "session": self.id,
                "name": self.name,
                "rev": self.rev,
                "saved_at": self.saved_at,
                "status": self.status,
                "images": [
                    {
                        "id": e.id,
                        "name": e.name,
                        "source": e.source,
                        "size": e.size,
                        "refreshable": e.refreshable,
                        "items": [dict(it) for it in self.items.get(e.id, [])],
                    }
                    for e in (self.images[i] for i in self.order)
                ],
            }

    def status_dict(self) -> dict:
        with self._cond:
            elapsed = round(time.time() - self.created, 1)
            return {
                "session": self.id,
                "status": self.status,
                "rev": self.rev,
                "saved_at": self.saved_at,
                "items_count": sum(len(v) for v in self.items.values()),
                "images": len(self.order),
                "elapsed_s": elapsed,
            }

    def apply_save(self, payload: dict) -> dict:
        """Called from the HTTP thread when the user hits 保存."""
        raw_images = payload.get("images")
        if raw_images is None and "items" in payload:  # single-image shorthand
            raw_images = [{"id": self.order[0], "items": payload.get("items") or []}]
        if not isinstance(raw_images, list):
            raise ValueError("payload 需要 images: [{id, items}]。")

        incoming: dict[str, list] = {}
        for block in raw_images:
            if not isinstance(block, dict):
                raise ValueError("images 的每一项必须是对象。")
            iid = block.get("id") or self.order[0]
            if iid not in self.images:
                raise ValueError(f"未知图片 id {iid!r}；这个会话里有 {self.order}。")
            incoming[iid] = block.get("items") or []

        cleaned: dict[str, list[dict]] = {}
        stats = []
        for iid, raw in incoming.items():
            entry = self.images[iid]
            items, clamped = _clean_items(raw, *entry.size)
            cleaned[iid] = items
            stats.append({"id": iid, "items": len(items), "clamped": clamped})

        with self._cond:
            for iid, items in cleaned.items():
                self.items[iid] = items
            self.rev += 1
            self.saved_at = time.strftime("%Y-%m-%d %H:%M:%S")
            self.status = "saved"
            self._cond.notify_all()

        return {
            "ok": True,
            "session": self.id,
            "rev": self.rev,
            "saved_at": self.saved_at,
            "images": stats,
            "total_items": sum(len(v) for v in cleaned.values()),
        }

    def wait(self, since_rev: int = 0, timeout_s: float = 240.0) -> dict:
        """Block until a save newer than ``since_rev`` arrives, or timeout."""
        started = time.monotonic()
        with self._cond:
            self._cond.wait_for(
                lambda: self.rev > since_rev or self.status == "cancelled",
                timeout=max(0.0, float(timeout_s)),
            )
            elapsed = round(time.monotonic() - started, 1)
            if self.status == "cancelled":
                status = "cancelled"
                hint = "会话已取消，别再等了；需要标注就重新调用 annotate_image。"
            elif self.rev > since_rev:
                status = "saved"
                hint = "已拿到标注结果。需要用户补标，就用 since_rev 再等一次。"
            else:
                status = "pending"
                hint = (
                    f"用户还没点保存（已等 {elapsed}s）。可以再调一次 "
                    "annotate_wait 继续等，或先做别的事再回来查 annotate_status。"
                )
            out = self.snapshot()
            out.update({"status": status, "elapsed_s": elapsed, "hint": hint})
            return out

    def cancel(self) -> None:
        with self._cond:
            self.status = "cancelled"
            self._cond.notify_all()
        self.close()

    # -- http server ----------------------------------------------------

    def close(self) -> None:
        srv = self.httpd
        if srv is not None:
            self.httpd = None
            # shutting down a dying server is best-effort by definition
            with contextlib.suppress(Exception):
                srv.shutdown()
            with contextlib.suppress(Exception):
                srv.server_close()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Session {self.id} {self.name!r} rev={self.rev} {self.status}>"


class SessionManager:
    """Owns every live session. One manager per process."""

    def __init__(self, base_port: int = 8777, auto_open: bool = True) -> None:
        self.base_port = base_port
        self.auto_open = auto_open
        self._sessions: dict[str, Session] = {}
        self._counter = 0
        self._lock = threading.Lock()

    # -- lifecycle ------------------------------------------------------

    def create(
        self,
        name: str | None = None,
        sources: object = None,
        resize_to: list[int] | None = None,
    ) -> Session:
        with self._lock:
            self._counter += 1
            sid = f"s{self._counter}"
            session = Session(sid, (name or "board_ui").strip() or "board_ui")

        items = sources if isinstance(sources, list) else [sources]
        for src in items:
            img, meta = load_image(src, resize_to=resize_to)
            session.add_image(img, meta)

        self._start_http(session)
        with self._lock:
            self._sessions[sid] = session

        if self.auto_open and session.url:
            threading.Thread(target=_safe_open, args=(session.url,), daemon=True).start()
        return session

    def _start_http(self, session: Session) -> None:
        from .httpd import make_server

        server, port = make_server(session, self.base_port)
        session.httpd = server
        session.port = port
        session.url = f"http://127.0.0.1:{port}/?s={session.id}"
        thread = threading.Thread(
            target=server.serve_forever,
            name=f"annotate-http-{session.id}",
            daemon=True,
        )
        thread.start()
        session._http_thread = thread

    # -- access ---------------------------------------------------------

    def get(self, sid: str | None) -> Session:
        with self._lock:
            if sid is None and self._sessions:
                # No id given: hand back the newest session, that is almost always
                # what a single-session user means.
                return list(self._sessions.values())[-1]
            session = self._sessions.get(sid or "")
        if session is None:
            alive = sorted(self._sessions)
            raise SessionError(
                f"没有会话 {sid!r}；当前活着的会话是 {alive or '（无）'}。"
                "需要新的标注就先调用 annotate_image。"
            )
        return session

    def cancel(self, sid: str) -> bool:
        with self._lock:
            session = self._sessions.pop(sid, None)
        if session is None:
            return False
        session.cancel()
        return True

    def list_sessions(self) -> list[dict]:
        with self._lock:
            return [s.status_dict() for s in self._sessions.values()]

    def close_all(self) -> None:
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            session.cancel()


def _safe_open(url: str) -> None:
    # headless boxes have no browser; the URL is still returned either way
    with contextlib.suppress(Exception):
        webbrowser.open(url)


_MANAGER: SessionManager | None = None
_MANAGER_LOCK = threading.Lock()


def configure(base_port: int = 8777, auto_open: bool = True) -> None:
    """Reset the process-wide manager (used by the CLI and by tests)."""
    global _MANAGER
    with _MANAGER_LOCK:
        if _MANAGER is not None:
            _MANAGER.close_all()
        _MANAGER = SessionManager(base_port=base_port, auto_open=auto_open)


def get_manager() -> SessionManager:
    global _MANAGER
    with _MANAGER_LOCK:
        if _MANAGER is None:
            _MANAGER = SessionManager()
        return _MANAGER


def reset_manager() -> None:
    global _MANAGER
    with _MANAGER_LOCK:
        if _MANAGER is not None:
            _MANAGER.close_all()
        _MANAGER = None
