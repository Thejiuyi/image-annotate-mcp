# Data model

Everything below is what `annotate_wait` / `annotate_load` return, and what lands in
`annotations/<name>.json` on disk. The two are the same object — the file is not a
summary.

## Top level

```json
{
  "schema": 2,
  "session": "s3",
  "name": "inventory",
  "rev": 2,
  "saved_at": "2026-11-16T14:55:15+08:00",
  "status": "saved",
  "images": [ ... ]
}
```

| field | meaning |
|---|---|
| `rev` | monotonic save counter. Pass it as `since_rev` to wait only for the **next** save |
| `status` | `pending` (still drawing), `saved`, or `cancelled` |
| `saved_at` | when the last save happened; `null` before the first one |

## An image

```json
{
  "id": "img1",
  "name": "shot.png",
  "source": "/path/to/shot.png",
  "size": [1280, 720],
  "refreshable": false,
  "items": [ ... ]
}
```

`size` is `[width, height]` of the **original** image. `refreshable` is `true` for live
screen captures, which can be re-captured without starting a new session.

## An item

Key order is fixed — `index`, `name`, `type`, geometry, `note`, `hidden` — because that is
what a human diffs when comparing two annotation files.

| `type` | geometry | template? |
|---|---|---|
| `box` | `box: [x, y, w, h]` | yes — the cropped rectangle |
| `point` | `point: [x, y]` | **no** — there is nothing to crop |
| `polygon` | `points: [[x, y], ...]` plus `bbox: [x, y, w, h]` | yes — masked to the outline |

`bbox` on a polygon is the bounding rectangle of its vertices, in the same `[x, y, w, h]`
shape as a box, so code that only understands boxes can still use it.

Other fields:

- `note` — free text the user typed, `""` when empty.
- `hidden` — present and `true` when the user hid the item while drawing. A hidden item is
  **still cropped and still listed**; it is only omitted from rendered pictures. Treat it
  as "exists but the user does not want to see it", not as deleted.
- `template` — filename (not a path) inside `templates/`. Resolve it against the
  `data_dir` returned by `annotate_image`.

### Template files

- `box` → an RGB PNG, exactly the pixels inside the box.
- `polygon` → an **RGBA** PNG, cropped to the vertex bounding box and then masked to the
  outline: everything outside the polygon is fully transparent. Do not re-crop it by its
  rectangle, or you lose the point of the polygon.
- `point` → no template at all. Use a point when you only need to click at a coordinate;
  use a small box when you need pixels for template matching.

## Coordinates

- Origin is the top-left of the **original** image; `y` grows downward.
- Units are original-image pixels. The page's zoom level, the browser's device pixel
  ratio, and `resize_to` do not leak into these numbers — except that `resize_to`
  redefines what "the original image" is for that session.
- Values are integers. Boxes are clamped into the image: a box dragged past an edge comes
  back with the edge as its boundary, and the save response reports how many items were
  clamped.

## On disk

```
<data_dir>/
├── annotations/
│   ├── inventory.json     # the payload above
│   └── inventory.md       # the same thing as a human-readable table
├── templates/
│   └── inventory__img1__item1.png
└── sources/
    └── inventory__img1.png    # snapshot of the base image
```

Names are slugified to ASCII: a Chinese name like `按钮` becomes `item1` in the filename
(duplicates get `_2`, `_3`, …). The **`name` field in the JSON keeps the original text** —
only filenames are ASCII. So look up templates through the `template` field, never by
reconstructing the filename from the name.
