---
name: image-annotate
description: Ask the human where something is on screen and get back original-image pixel coordinates, a semantic name, and a cropped template image. Use whenever you need a coordinate you cannot know for sure — locating a button/icon/region in a game or app screenshot, building template-matching targets, clicking something whose position differs between runs, or when the user says "点这里" / "框一下这个" / "this button" while showing a screenshot. Opens a local browser page where the user draws a box, a point, or a polygon. Never guess coordinates from pixels and never OCR a button label to find it.
---

# Annotating images with a human in the loop

You cannot reliably guess where a button is from pixels, and guessing wrong costs a
round trip. Ask the human to point at it instead. One drag gives you three things at
once: **pixel coordinates in the original image**, a **semantic name**, and a **cropped
template** ready for template matching.

## The loop

**1. Open a session**

```
annotate_image(source="shot.png", name="inventory")
```

- `source` — a local path, a data URL, raw base64, `"screen"` (live capture, the default
  when omitted), or a **list** of any of those for a multi-image session.
- `name` — session name; also the filename the annotation is saved under.
- `resize_to=[w, h]` — only when the image is far larger than the user's screen. It
  **changes the coordinate space**, so leave it out unless you have to.

Returns `session`, `url`, `images[]`, `data_dir`.

**2. Ask the user to open `url`** and say exactly what you want, in their words:

> 在打开的页面上框出「商店」按钮，命名为 shop，然后点保存。

The page opens by itself unless you pass `open_browser=false`. Modes: `1` box,
`2` point, `3` polygon (click each vertex, then `Enter` / double-click / click the first
vertex to close). Wheel zooms, middle-drag pans, `H` hides annotations.

**3. Wait for the save**

```
annotate_wait(session="<id>", timeout_s=240)
```

**4. Read the result** — `status: "saved"`, then walk `images[].items[]`.

**5. Close the session** with `annotate_cancel(session=...)` when you no longer need it.

## What an item looks like

```json
{
  "index": 1,
  "name": "shop",
  "type": "box",
  "box": [40, 520, 180, 80],
  "template": "/home/me/.image-annotate-mcp/annotations/templates/inventory__img1__item1.png"
}
```

| `type` | payload | meaning |
|---|---|---|
| `box` | `box: [x, y, w, h]` | top-left corner plus size — the normal case |
| `point` | `point: [x, y]` | a click target — **no template** is cropped for it |
| `polygon` | `points: [[x, y], ...]` and `bbox: [x, y, w, h]` | irregular region; the template is masked to the outline |

All coordinates are **original-image pixels**, top-left origin, unaffected by zoom or
device pixel ratio.

`template` is a real PNG on disk, but it only exists for `box` and `polygon` — a point has
nothing to crop. Use a point when you just need to click at a coordinate; use a box when
you need the pixels for template matching. Polygon templates are RGBA, with everything
outside the outline transparent.

`hidden: true` means the user hid that item while drawing. It is still cropped and still
listed; just do not draw it in your own output.

## If it times out

`status: "pending"` is **not an error** — the user has not clicked save yet. Call
`annotate_wait` again with the same `since_rev`. After a save, pass the returned `rev` as
`since_rev` so you only wake for the next save instead of re-reading the old one.

Keep `timeout_s` **below your MCP client's own tool timeout**, otherwise the client gives
up first and the server's clean `pending` never reaches you. If the client kills the call,
raise the client timeout rather than the server one.

## Look at the picture yourself

You do not have to ask the user to type names. Render the numbered overlay and read it:

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

Emits coordinate constants plus a `TEMPLATES` map, which is usually all a
template-matching loop needs. `fmt="json"` / `fmt="yaml"` dump the raw payload.

## Reuse what was already annotated

```
annotate_list()                  # newest first
annotate_load(name="inventory")  # full payload, no new session needed
```

If the user annotated this screen before, load it instead of asking them to draw again.

## Do not

- **Do not guess coordinates and skip the annotation** when the user's screenshot is
  right there. One annotation round beats three wrong clicks.
- **Do not call `annotate_image` twice** for the same task — reuse the open session and
  `since_rev`.
- **Do not send the user the whole payload** and ask them to verify numbers. Show the
  rendered picture, or state the names and let them correct you.
- **Do not resize** (`resize_to`) unless the image genuinely does not fit on their
  screen; every coordinate downstream is in the resized space.
