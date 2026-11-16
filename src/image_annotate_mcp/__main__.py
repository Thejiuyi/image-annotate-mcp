"""Console entry point: ``annotate-mcp``.

Runs the MCP server over stdio. Everything the user might want to configure is a
flag here, so the ``mcpServers`` JSON snippet stays short.

Nothing in this process may write to stdout -- that stream carries the
JSON-RPC frames.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from . import __version__
from . import sessions as sessions_mod


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="annotate-mcp",
        description="MCP server for human-in-the-loop image annotation.",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Where annotations/templates/exports live (default: ~/.image-annotate-mcp).",
    )
    parser.add_argument(
        "--base-port",
        type=int,
        default=8777,
        help="First port to try for the annotation page; it counts up if taken (default: 8777).",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Do not launch a browser automatically; just return the URL.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args, unknown = parser.parse_known_args(argv)
    if unknown:
        logging.getLogger(__name__).debug("ignoring unknown args: %s", unknown)

    if args.data_dir:
        os.environ["IMAGE_ANNOTATE_DATA_DIR"] = os.path.abspath(os.path.expanduser(args.data_dir))

    logging.basicConfig(
        stream=sys.stderr,
        level=logging.INFO,
        format="[image-annotate-mcp] %(levelname)s %(message)s",
    )

    sessions_mod.configure(base_port=args.base_port, auto_open=not args.no_open)

    from .server import mcp

    try:
        mcp.run("stdio")
    except KeyboardInterrupt:
        pass
    finally:
        sessions_mod.reset_manager()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
