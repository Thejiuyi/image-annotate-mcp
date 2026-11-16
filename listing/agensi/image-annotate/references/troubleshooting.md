# Troubleshooting

Each entry: the symptom you will actually see, then the action.

## `status: "pending"` comes back

Not an error. The user has not clicked 保存 yet. Call `annotate_wait` again with the same
`since_rev`. If they are still drawing, tell them what you are waiting for rather than
polling in silence.

## `MCP error -32001: Request timed out`

The **client's** timeout fired before the server's. Raise the timeout in the client config
(Claude Code uses `timeout` in the server entry, in milliseconds), and/or lower
`timeout_s`. Do not raise only the server's timeout — that makes it worse.

## The page does not open

1. Read the `url` out of the `annotate_image` response and give it to the user directly —
   auto-open can be blocked, especially on macOS and Linux.
2. On Windows the first run may pop a firewall prompt for Python. Allow it, or the page
   loads but never talks to the server.
3. If the URL opens but stays blank, the session may have been cancelled. Check
   `annotate_status`.

## `端口 8777–8796 全被占用`

The default port range is taken (usually by earlier sessions that were not closed). Start
the server with a different range:

```bash
annotate-mcp --base-port 9000
```

## `curl` or `requests` to `127.0.0.1` fails with a proxy error

A local proxy (Clash, Surge, corporate VPN) is intercepting loopback traffic. Use
`--noproxy '*'` for curl, or set `NO_PROXY=127.0.0.1`. This only affects **your own**
diagnostics — the agent talking over MCP is not affected.

## Saving a polygon fails with `面积是 0`

The vertices are all on one line, so the crop would be a fully transparent PNG: the user
would think it saved and you would get an invisible template. Ask them to re-click the
outline, or use a box instead.

## A box came back clipped to the image edge

Expected. Boxes are clamped into the image, and the save response reports how many items
were clamped. If the clamp matters, ask the user to redraw inside the image.

## Template files look stale

Re-saving under the same name overwrites the JSON, the Markdown, and the templates of the
items that still exist. Templates of items the user **deleted** are deliberately left on
disk — the tool does not delete data on your behalf. Clear `templates/` yourself if you
need a clean slate.

## The coordinates are right but the click misses

Check that the consumer uses the **original** image, not a resized copy. If the app
screenshots at a different resolution than the one annotated, scale by
`annotated_size / runtime_size` before clicking. `annotate_export(fmt="py")` writes the
`SIZE` constant for exactly this reason.

## `annotate_image` fails with a path error

`source` must be a path the **server process** can read — not a path in the agent's
sandbox. When in doubt, pass `source="screen"` and let the server capture the screen
itself.
