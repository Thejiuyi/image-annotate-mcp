"""Turn whatever the agent handed us into a PIL image.

Accepted sources, in the order they are tried:

1. ``None`` / ``"screen"`` / ``"screen:2"`` -- grab a live screen (optional).
2. ``data:image/...;base64,...`` -- a data URL.
3. An existing file path.
4. An ``http(s)://`` URL.
5. A raw base64 string of an image.

Everything is normalised to ``RGB``/``RGBA`` PIL image; EXIF rotation is applied so
what the user sees in the browser is what the coordinates refer to.
"""

from __future__ import annotations

import base64
import binascii
import io
import re
from pathlib import Path
from urllib.request import Request, urlopen

from PIL import Image, ImageOps

__all__ = ["SourceError", "load_image", "grab_screen", "screen_available"]

SCREEN_HINT = (
    "抓屏需要可选依赖，先安装：pip install image-annotate-mcp[screen]；"
    "或者把图片路径 / base64 传给 source。"
)
_SCREEN_HINT_EN = (
    "Screen capture needs an optional dependency: pip install image-annotate-mcp[screen]; "
    "alternatively pass a file path or base64 string as `source`."
)

_B64_RE = re.compile(r"^[A-Za-z0-9+/=\s]+$")
_DATA_URL_RE = re.compile(r"^data:image/[A-Za-z0-9.+-]+;base64,(.*)$", re.S)


class SourceError(RuntimeError):
    """Raised when a source cannot be turned into an image.

    The message always tells the caller what to do next, not just what went wrong.
    """


def screen_available() -> bool:
    """True when *some* screen capture backend is importable on this machine."""
    try:
        import mss  # noqa: F401
    except Exception:  # noqa: BLE001 - any import failure means "not available"
        pass
    else:
        return True
    try:
        from PIL import ImageGrab
    except Exception:  # noqa: BLE001
        return False
    # ImageGrab exists on every platform, but on Linux it shells out to
    # gnome-screenshot / scrot / grim and fails at call time. Probe cheaply.
    return hasattr(ImageGrab, "grab")


def grab_screen(index: int = 1) -> tuple[Image.Image, str]:
    """Grab one monitor. ``index`` 0 = the whole virtual desktop, 1 = primary."""
    try:
        import mss

        with mss.mss() as sct:
            monitors = sct.monitors
            if not monitors:
                raise SourceError(_SCREEN_HINT_EN)
            if index < 0 or index >= len(monitors):
                index = 1 if len(monitors) > 1 else 0
            shot = sct.grab(monitors[index])
            img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
            return img, "mss"
    except SourceError:
        raise
    except ImportError:
        pass
    except Exception as exc:  # noqa: BLE001 - mss installed but failed (no display, etc.)
        raise SourceError(f"抓屏失败（mss）：{exc!r}。{SCREEN_HINT}") from exc

    try:
        from PIL import ImageGrab

        img = ImageGrab.grab()
        return img.convert("RGB"), "PIL.ImageGrab"
    except Exception as exc:  # noqa: BLE001
        raise SourceError(f"抓屏失败（ImageGrab）：{exc!r}。{SCREEN_HINT}") from exc


def _decode_base64(payload: str) -> bytes:
    cleaned = re.sub(r"\s+", "", payload)
    try:
        return base64.b64decode(cleaned, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SourceError(
            "base64 解码失败：字符串不是合法的 base64。"
            "请检查是不是少了补位的 '='，或者把整段 data URL 一起传进来。"
        ) from exc


def _open_bytes(raw: bytes) -> Image.Image:
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except Exception as exc:  # noqa: BLE001
        raise SourceError(
            f"这段数据不是可识别的图片（{exc!r}）。支持 PNG/JPEG/WebP/BMP/GIF/TIFF。"
        ) from exc
    return img


def _normalise_mode(img: Image.Image) -> Image.Image:
    """Keep alpha if present, otherwise force RGB (so JPEG encoding always works)."""
    if img.mode in ("RGB", "RGBA"):
        return img
    if img.mode in ("LA", "P", "PA"):
        return img.convert("RGBA")
    return img.convert("RGB")


def load_image(
    source: object,
    resize_to: list[int] | tuple[int, int] | None = None,
) -> tuple[Image.Image, dict]:
    """Resolve ``source`` into ``(image, meta)``.

    ``meta`` always carries ``source``, ``name``, ``size_before`` and ``size_after``
    so the agent can tell whether coordinates refer to the original file.
    """
    if source is None:
        img, backend = grab_screen(1)
        meta = {
            "source": "screen:1",
            "name": "screen",
            "capture_backend": backend,
            "refreshable": True,
        }
        img = _normalise_mode(img)
        meta["size_before"] = list(img.size)
    elif isinstance(source, str) and source.strip().lower().startswith("screen"):
        m = re.match(r"^screen(?::(\d+))?$", source.strip().lower())
        idx = int(m.group(1)) if (m and m.group(1)) else 1
        img, backend = grab_screen(idx)
        meta = {
            "source": f"screen:{idx}",
            "name": f"screen{idx}",
            "capture_backend": backend,
            "refreshable": True,
        }
        img = _normalise_mode(img)
        meta["size_before"] = list(img.size)
    elif not isinstance(source, str):
        raise SourceError(
            "source 必须是字符串（路径 / data URL / base64 / 'screen'）或字符串列表。"
        )
    else:
        text = source.strip()
        m = _DATA_URL_RE.match(text)
        if m:
            img = _normalise_mode(_open_bytes(_decode_base64(m.group(1))))
            meta = {"source": "data-url", "name": "inline", "refreshable": False}
            meta["size_before"] = list(img.size)
        else:
            path = Path(text).expanduser()
            if path.is_file():
                try:
                    raw = path.read_bytes()
                except OSError as exc:
                    raise SourceError(f"读不到文件 {path}：{exc}") from exc
                img = _normalise_mode(ImageOps.exif_transpose(_open_bytes(raw)))
                meta = {
                    "source": f"file:{path.resolve()}",
                    "name": path.name,
                    "refreshable": False,
                }
                meta["size_before"] = list(img.size)
            elif text.startswith(("http://", "https://")):
                try:
                    req = Request(text, headers={"User-Agent": "image-annotate-mcp"})
                    with urlopen(req, timeout=20) as resp:  # noqa: S310 - user supplied URL
                        raw = resp.read()
                except Exception as exc:  # noqa: BLE001
                    raise SourceError(
                        f"下载图片失败：{exc!r}。若在代理环境下，检查 NO_PROXY / 直连设置，"
                        "或者先把图存到本地再传路径。"
                    ) from exc
                img = _normalise_mode(_open_bytes(raw))
                meta = {
                    "source": text,
                    "name": text.rsplit("/", 1)[-1] or "remote",
                    "refreshable": False,
                }
                meta["size_before"] = list(img.size)
            elif len(text) >= 64 and _B64_RE.match(text):
                img = _normalise_mode(_open_bytes(_decode_base64(text)))
                meta = {"source": "base64", "name": "inline", "refreshable": False}
                meta["size_before"] = list(img.size)
            else:
                raise SourceError(
                    f"找不到这个图片：{text!r}。"
                    "source 支持：本地绝对路径 / data URL / base64 / 'screen'。"
                )

    if resize_to:
        if len(resize_to) != 2:
            raise SourceError("resize_to 需要 [宽, 高] 两个整数。")
        target = (int(resize_to[0]), int(resize_to[1]))
        if target[0] <= 0 or target[1] <= 0:
            raise SourceError("resize_to 的宽高必须为正数。")
        if tuple(img.size) != target:
            img = img.resize(target, Image.LANCZOS)
            meta["resized"] = True

    meta["size_after"] = list(img.size)
    return img, meta
