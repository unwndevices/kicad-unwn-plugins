#!/usr/bin/env python3
"""Regenerate the toolbar icons for the return-path checker IPC plugin.

Draws a small "return-path" glyph — a signal trace running left-to-right across a
ground plane that has a slot/gap beneath it, with the crossing flagged (the classic
split-plane return-path defect this tool finds) — in a light and a dark variant, at
the sizes KiCad expects. Run from this directory:  ``python make_icons.py``.

Pillow only; deterministic. The PNGs it writes are committed, so contributors need
not run this unless they change the artwork.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

SS = 8  # supersample factor for crisp anti-aliased edges
SIZES = (24, 48)
HERE = Path(__file__).resolve().parent

# (foreground, plane, accent) per theme. "light" = icons for KiCad's light UI (dark
# glyph); "dark" = for the dark UI (light glyph). Accent is a warning red (the flagged
# crossing); plane is a muted copper/green.
THEMES = {
    "light": ((43, 43, 43, 255), (58, 125, 84, 255), (210, 59, 59, 255)),
    "dark": ((232, 232, 232, 255), (90, 170, 120, 255), (232, 90, 90, 255)),
}


def _draw(size: int, fg: tuple, plane: tuple, accent: tuple) -> Image.Image:
    s = size * SS
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    margin = round(s * 0.12)
    # ground plane: a filled band across the lower half, split by a vertical gap.
    plane_top = round(s * 0.52)
    plane_bot = s - margin
    gap_w = round(s * 0.14)
    gap_x0 = (s - gap_w) // 2
    d.rectangle((margin, plane_top, gap_x0, plane_bot), fill=plane)
    d.rectangle((gap_x0 + gap_w, plane_top, s - margin, plane_bot), fill=plane)

    # signal trace: a horizontal run across the upper third, over the gap.
    trace_y = round(s * 0.30)
    stroke = max(SS, round(s * 0.07))
    d.line((margin, trace_y, s - margin, trace_y), fill=fg, width=stroke)

    # the flagged crossing: a red ring where the trace passes over the plane gap.
    cx = s // 2
    r = round(s * 0.11)
    ring = max(SS, round(s * 0.05))
    d.ellipse((cx - r, trace_y - r, cx + r, trace_y + r), outline=accent, width=ring)

    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    for theme, (fg, plane, accent) in THEMES.items():
        for size in SIZES:
            img = _draw(size, fg, plane, accent)
            out = HERE / f"icon-{theme}-{size}.png"
            img.save(out)
            print(f"wrote {out.name}")


if __name__ == "__main__":
    main()
