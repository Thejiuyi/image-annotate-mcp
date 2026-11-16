from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    """Point the whole package at a throwaway data directory."""
    target = tmp_path / "data"
    monkeypatch.setenv("IMAGE_ANNOTATE_DATA_DIR", str(target))
    return target


@pytest.fixture()
def sample_png(tmp_path):
    """A deterministic 320x200 image with one 100x60 red rectangle at (40,50)."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (320, 200), (20, 30, 40))
    draw = ImageDraw.Draw(img)
    draw.rectangle([40, 50, 139, 109], fill=(200, 60, 70))
    path = tmp_path / "shot.png"
    img.save(path)
    return path


@pytest.fixture()
def manager(data_dir):
    from image_annotate_mcp import sessions

    sessions.configure(base_port=8930, auto_open=False)
    yield sessions.get_manager()
    sessions.reset_manager()


@pytest.fixture()
def session(manager, sample_png):
    return manager.create(name="board_ui", sources=str(sample_png))
