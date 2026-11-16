# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning follows [SemVer](https://semver.org/).

## [Unreleased]

### Added

- **`skills/image-annotate/SKILL.md`** — an Agent Skill for clients that load them. The
  tool descriptions say what each tool does; this file says when to reach for them, and
  spells out the loop (open → user draws → wait → read → cancel) plus the mistakes agents
  make without being told: guessing coordinates, calling `annotate_image` twice, treating
  `status="pending"` as an error, and resizing the image so every downstream coordinate
  shifts. Also documents that `point` items carry no `template` — only `box` and `polygon`
  get cropped.

## [0.3.0] - 2026-11-15

### Added

- **Wheel zoom** (on by default) — zooms around the cursor from 1x to 16x, so you can
  place a vertex on one pixel instead of guessing at 84% scale. Stroke widths, label
  chips and drag handles are divided by the zoom factor, so they stay the same size
  on screen while the image grows. Pan with `Space`+drag or a middle-button drag;
  `Ctrl+0` or the percentage button resets to fit.
- **Loupe** (off by default, `L`) — a draggable floating window showing an N x N
  region of *original image pixels* magnified (N = 40/60/80/120, i.e. 5x down to
  1.7x), with the pixel under the cursor outlined and short reticle ticks pointing at
  it. Drag its title bar to pin it elsewhere; the button there toggles back to
  auto-follow. It samples the image itself, so annotations never cover the pixels
  you are inspecting.
- A view bar in the bottom-left corner: `-` / percentage / `+`, the wheel-zoom
  toggle, the loupe toggle and its sample size.

### Changed

- The stage is now a fixed-height viewport (`overflow: hidden`) instead of a
  full-width image that scrolled the page. The image is fitted with *contain*, so
  the whole screenshot is always visible at 100%.
- The canvas covers the viewport and carries the zoom/pan transform, so annotation
  hit-testing still works in one coordinate space (`viewPt` converts viewport pixels
  to fit pixels once, at the event boundary).

### Fixed

- Hidden items are skipped by hit-testing as well as by drawing — clicking where a
  hidden item used to be no longer selects it.

## [0.2.0] - 2026-11-15

### Added

- **Polygon items** (`type: "polygon"`) — a third tool (`3`) for irregular shapes
  joined by straight segments: click each vertex, then close it by clicking the first
  vertex, double-clicking, or pressing `Enter`. `Backspace` drops the last vertex,
  `Esc` abandons the outline. The saved item carries `points` (the vertices) and
  `bbox` (their bounding rectangle).
- **Masked polygon templates** — the crop is the vertex bbox with everything outside
  the outline made transparent, so `templates/*.png` holds the irregular region
  rather than its bounding rectangle. Polygon templates are `RGBA`; box templates
  stay `RGB`.
- **Hidden layers** — an eye button per row (persisted as `hidden: true`) hides one
  item, and `H` hides every annotation so you can look at the screenshot underneath.
  Hidden items keep their template and their row; only drawing is suppressed — in
  the page and in `fmt="png"` / `annotate_render` output.

### Fixed

- A polygon whose vertices are collinear is refused at save time. It would otherwise
  produce a fully transparent template that looks exactly like a successful save.
- The sidebar's polygon `bbox` text was one pixel wider than the `bbox` in the saved
  JSON (`max - min + 1` vs `max - min`); both now follow the box convention.

### Changed

- `annotate_wait` items gained `points` / `bbox` for polygons and the optional
  `hidden` flag. `box` and `point` items are unchanged from 0.1.0, so existing
  consumers keep working.

## [0.1.0] - 2026-11-15

First release. Rebuilt from a single-file prototype (`annotate.py`) into a package.

### Added

- **Eight MCP tools**: `annotate_image`, `annotate_wait`, `annotate_status`,
  `annotate_cancel`, `annotate_list`, `annotate_load`, `annotate_export`,
  `annotate_render`.
- **Blocking handshake** — `annotate_wait` parks on a `threading.Condition` until the
  user saves; timeout returns `status: "pending"` instead of raising, so an agent can
  simply wait again. `since_rev` makes repeated waits incremental.
- **Multi-image sessions** — one session can carry several images, each with its own
  items, size and template namespace; the page shows a tab strip.
- **Numbered export** (`fmt="png"`) plus `annotate_render`, which returns the picture
  as image content so a multimodal agent can read the labels itself.
- **Code export** (`fmt="py"`) with coordinate constants, a template map and the
  original (often Chinese) names preserved as comments.
- **JSON / YAML export** without a PyYAML dependency.
- **v1 read compatibility** — annotation files written by the old prototype load
  fine and are never rewritten.
- Base-image snapshots under `sources/`, so exports keep working after the original
  screenshot is gone.

### Changed from the prototype

- Dropped OpenCV for Pillow; the only hard dependencies are `mcp` and `pillow`.
- Screen capture is optional (`pip install image-annotate-mcp[screen]`, uses `mss`)
  and falls back to `PIL.ImageGrab` on Windows/macOS.
- No more forced 1920×1080 normalisation — `resize_to` is opt-in and the result
  reports `size_before` / `size_after`.
- Real undo/redo stack (the prototype's "撤销" was actually "delete last").
- Boxes can be moved and resized with eight handles.
- Canvas honours `devicePixelRatio`, so coordinates are not off by half a pixel on
  HiDPI screens.
- All logging goes to stderr; stdout is reserved for the JSON-RPC transport.

### Fixed

- A save could wake a waiting agent *before* the template crops were written, so
  `annotate_wait` sometimes returned items with no `template`. Saving is now atomic.
- Marks are drawn with a dark under-stroke, so a red box on a red button (or a
  yellow crosshair on a yellow button) is still legible.

### Known gaps

- No animated demo GIF in the repository yet; `docs/screenshot.png` and
  `docs/annotated.png` cover the same ground statically.
- MCP Apps (SEP-1865) is not used — the UI opens in a browser tab. The page is a
  self-contained resource, so it can be embedded later without a rewrite.
