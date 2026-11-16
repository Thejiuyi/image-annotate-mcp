"""image-annotate-mcp -- human-in-the-loop image annotation over MCP.

The user draws boxes and points on a screenshot in a local web page; the agent
gets pixel coordinates, names and cropped template images back.

Typical flow::

    annotate_image(source="screen")          -> {"session": "s1", "url": "http://..."}
    annotate_wait(session="s1", timeout_s=240) -> {"images": [{"items": [...]}]}
"""

from __future__ import annotations

__version__ = "0.3.0"

__all__ = ["__version__"]
