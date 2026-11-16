# image-annotate

An agent skill that gets **exact pixel coordinates** out of a human instead of guessing
them from a screenshot.

You (the agent) cannot tell where a button is by looking at pixels. The user can — they
just need somewhere to click. This skill opens a local page showing their image; they
drag a box, click a point, or draw a polygon; and you get back:

- coordinates in **original-image pixels** (not screen pixels, not CSS pixels),
- the name they typed,
- and a cropped template PNG you can match against later.

## Requirements

| What | Why |
|---|---|
| Python 3.10+ | the backing MCP server is a Python package |
| The `image-annotate-mcp` server, registered in your MCP client | this skill drives it; it is not a standalone script |
| A browser on the same machine | that is where the user draws |
| A human, for about 10 seconds per annotation | this is human-in-the-loop by design |

## Setup

```bash
pip install "git+https://github.com/Thejiuyi/image-annotate-mcp"
```

Then register the server in your client's MCP config:

```json
{
  "mcpServers": {
    "image-annotate": { "command": "annotate-mcp", "args": [] }
  }
}
```

Restart the client. Verify with `scripts/check_setup.py`, which only reads — it installs
nothing and changes nothing.

Live screen capture additionally needs `mss`:

```bash
pip install mss
```

## What is in here

```
image-annotate/
├── SKILL.md                        the loop: open → user draws → wait → read → cancel
├── references/
│   ├── data-model.md               every field, coordinate rules, template semantics
│   └── troubleshooting.md          timeouts, busy ports, proxy on loopback, stale templates
├── examples/
│   └── session-walkthrough.md      a full worked example with real payloads
└── scripts/
    └── check_setup.py              read-only diagnosis of the prerequisites
```

## Honest limits

- **It needs a human.** There is no unattended mode; that is the entire point. If you need
  coordinates without a human, this is the wrong tool.
- **It needs a local server.** This is not a prompt-only skill — the value is in a real
  program that crops pixels and serves a page.
- **The first run is the slow one.** Install + client config + restart. After that a
  session is one tool call.

## Licence

MIT. The full source, tests, and the web UI are at
<https://github.com/Thejiuyi/image-annotate-mcp> — if you would rather read the code than
trust the listing, everything is there.
