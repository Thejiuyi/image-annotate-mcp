"""Ports: the second session must not steal the first one's page."""

from __future__ import annotations

import socket

import pytest

from image_annotate_mcp.httpd import make_server


def _occupy(port: int) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", port))
    sock.listen(1)
    return sock


def test_taken_port_rolls_to_the_next_one(session):
    blocker = _occupy(8960)
    server = None
    try:
        server, port = make_server(session, base_port=8960)
    finally:
        if server is not None:
            server.server_close()
        blocker.close()
    assert port == 8961


def test_each_session_gets_its_own_port(manager, sample_png):
    first = manager.create(name="a", sources=str(sample_png))
    second = manager.create(name="b", sources=str(sample_png))
    try:
        assert first.port != second.port
        assert first.url.endswith(f"?s={first.id}")
        assert second.url.endswith(f"?s={second.id}")
    finally:
        manager.close_all()


def test_exhausted_port_range_explains_what_to_do(session):
    blockers = [_occupy(p) for p in range(8940, 8943)]
    try:
        with pytest.raises(RuntimeError) as exc:
            make_server(session, base_port=8940, attempts=3)
        message = str(exc.value)
        assert "--base-port" in message
        assert "8940" in message
    finally:
        for sock in blockers:
            sock.close()
