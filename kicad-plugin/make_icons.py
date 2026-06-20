#!/usr/bin/env python3
"""Regenerate the toolbar icons for the KiCad IPC plugin.

Draws a small "segmented touch slider" glyph — four rounded electrode segments in a
row with one highlighted (the touched one) — in a light and a dark variant, at the
sizes KiCad expects. Run from this directory:  ``python make_icons.py``.

Pillow only; deterministic. The PNGs it writes are committed, so contributors need
not run this unless they change the artwork.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

SS = 8  # supersample factor for crisp anti-aliased edges
SIZES = (24, 48)
HERE = Path(__file__).resolve().parent

# (foreground, accent) per theme. "light" = icons for KiCad's light UI (dark glyph);
# "dark" = icons for the dark UI (light glyph). Accent is a KiCad-ish blue.
THEMES = {
    "light": ((43, 43, 43, 255), (26, 127, 212, 255)),
    "dark": ((232, 232, 232, 255), (78, 163, 232, 255)),
}


def _draw(size: int, fg: tuple, accent: tuple) -> Image.Image:
    s = size * SS
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    margin = round(s * 0.10)
    seg_h = round(s * 0.46)
    top = (s - seg_h) // 2
    gap = round(s * 0.06)
    n = 4
    total_w = s - 2 * margin
    seg_w = (total_w - (n - 1) * gap) / n
    radius = round(seg_w * 0.32)
    stroke = max(SS, round(s * 0.045))
    active = 1  # the highlighted (touched) electrode

    for i in range(n):
        x0 = margin + i * (seg_w + gap)
        box = (round(x0), top, round(x0 + seg_w), top + seg_h)
        if i == active:
            d.rounded_rectangle(box, radius=radius, fill=accent)
        else:
            d.rounded_rectangle(box, radius=radius, outline=fg, width=stroke)

    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    for theme, (fg, accent) in THEMES.items():
        for size in SIZES:
            img = _draw(size, fg, accent)
            out = HERE / f"icon-{theme}-{size}.png"
            img.save(out)
            print(f"wrote {out.name}")


if __name__ == "__main__":
    main()
