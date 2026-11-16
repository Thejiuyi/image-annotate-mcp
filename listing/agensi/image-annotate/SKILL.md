---
name: image-annotate
description: Use when the user asks where something is on a screenshot or on screen — phrases like "点这里", "框一下这个按钮", "where is the X", "annotate this screenshot", "give me the coordinates of this button", "make a template for this icon", "find this button on the screen". Opens a local page where the user drags a box, clicks a point, or draws a polygon, then returns original-image pixel coordinates, a name, and a cropped template PNG ready for template matching.
---

# image-annotate

Turns "where is that button?" into exact pixel coordinates, a semantic name, and a
cropped template image — by asking the human to point at it instead of guessing from
pixels.

This is the right tool when the answer depends on the user's own screen: a game HUD, an
internal admin panel, a desktop app, anything where you cannot read the layout from the
source. It is the wrong tool when the coordinates are already known.

## Before the first use

This skill drives the `image-annotate-mcp` server. Call `annotate_status` to check: if the
tool does not exist, the server is not installed or not registered yet, and the user has
to do it **once**:

1. Install it (Python 3.10 or newer):

   ```bash
   pip install "git+https://github.com/Thejiuyi/image-annotate-mcp"
   ```

2. Register it in the MCP client config:

   ```json
   {
     "mcpServers": {
       "image-annotate": { "command": "annotate-mcp", "args": [] }
     }
   }
   ```

3. Restart the client so it picks up the new server.

`scripts/check_setup.py` prints the same diagnosis and the exact command to run if you
would rather check from a shell. It only reads — it installs nothing.

If the server is missing, say so and stop. Do not fall back to guessing coordinates: a
guessed click is worse than an honest "I need one setup step first".

## The loop

**1. Open a session**

```
annotate_image(source="shot.png", name="inventory")
```

- `source` — a local file path, a data URL, raw base64, `"screen"` for a live capture
  (the default when omitted), or a **list** of any of those for a multi-image session.
- `name` — session name; the annotation is also saved under this name.
- `resize_to=[w, h]` — only when the image is much larger than the user's screen. It
  **changes the coordinate space** for everything downstream, so leave it out by default.

Returns `session`, `url`, `images[]`, `data_dir`.

**2. Ask the user to open `url`** and say exactly what you need, in their words:

> 在打开的页面上框出「商店」按钮，命名为 shop，然后点保存。

The page opens by itself unless you pass `open_browser=false`. Modes: `1` box, `2` point,
`3` polygon (click each vertex, then `Enter`, double-click, or click the first vertex to
close). Wheel zooms, middle-drag pans, `H` hides annotations.

**3. Wait for the save**

```
annotate_wait(session="<id>", timeout_s=240)
```

**4. Read the result** — `status: "saved"`, then walk `images[].items[]`.

**5. Close the session** with `annotate_cancel(session=...)` when you are done with it.

A single item looks like this:

```json
{
  "index": 1,
  "name": "shop",
  "type": "box",
  "box": [40, 520, 180, 80],
  "template": "/home/me/.image-annotate-mcp/annotations/templates/inventory__img1__item1.png"
}
```

`box` is `[x, y, w, h]` in **original-image pixels**, top-left origin, unaffected by the
page's zoom or the display's pixel ratio. Full field list, polygon and point shapes, and
what `template` contains: `references/data-model.md`.

## If it times out

`status: "pending"` is **not an error** — the user simply has not clicked save yet. Call
`annotate_wait` again with the same `since_rev`. After a save, pass the returned `rev` as
`since_rev` so you only wake for the next save.

Keep `timeout_s` **below the MCP client's own tool timeout**, or the client gives up first
and the server's clean `pending` never reaches you. Raise the client timeout rather than
the server one.

## Look at the picture yourself

You do not have to ask the user to type names:

```
annotate_export(name="inventory", fmt="png")
annotate_render(name="inventory")     # returns image content you can actually see
```

Each outline is labelled with its index, so you can match a label to a name without
another round trip. Hidden items are not drawn.

## Turn it into code

```
annotate_export(name="inventory", fmt="py")
```

Emits coordinate constants plus a `TEMPLATES` map — usually everything a template-matching
loop needs. `fmt="json"` and `fmt="yaml"` dump the raw payload.

## Reuse what was already annotated

```
annotate_list()                  # newest first
annotate_load(name="inventory")  # full payload, no new session needed
```

If the user annotated this screen before, load it instead of asking them to draw again.

## Do not

- **Do not guess coordinates** when the user's screenshot is right there. One annotation
  round beats three wrong clicks.
- **Do not open a second session** for the same task — reuse the open one and `since_rev`.
- **Do not send the raw payload** and ask the user to check numbers. Show the rendered
  picture, or state the names and let them correct you.
- **Do not use `resize_to`** unless the image genuinely does not fit on their screen.
