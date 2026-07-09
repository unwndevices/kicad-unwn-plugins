"""Vertical boundary waveforms shared between segment shapes.

An inter-electrode boundary is a polyline running the full height of the slider,
oscillating horizontally about a nominal x. Three slider shapes reduce to one
waveform with different parameters:

* ``rectangular``    -> a straight line (amplitude 0),
* ``chevron``        -> a **triangle** wave,
* ``interdigitated`` -> a **square** wave (comb teeth).

Buffering such a line by half the air gap and subtracting it from the slider
rectangle yields two interlocking electrodes separated by a uniform gap — see
:mod:`captouch.geometry.slider`.
"""

from __future__ import annotations

__all__ = ["boundary_points"]

Point = tuple[float, float]


def _triangle(t: float) -> float:
    """Unit triangle wave (period 1, range [-1, 1]); ``_triangle(0) == 0`` rising."""
    f = t % 1.0
    if f < 0.25:
        return 4.0 * f
    if f < 0.75:
        return 2.0 - 4.0 * f
    return 4.0 * f - 4.0


def boundary_points(
    x0: float,
    amp: float,
    n_teeth: int,
    y_lo: float,
    y_hi: float,
    kind: str,
) -> list[Point]:
    """Return the vertices of a boundary polyline from ``y_lo`` up to ``y_hi``.

    Parameters
    ----------
    x0:
        Nominal (mean) x of the boundary.
    amp:
        Horizontal half-amplitude. ``0`` (or ``kind == "rectangular"``) yields a
        straight vertical line at ``x0``.
    n_teeth:
        Number of oscillation periods (chevron) / comb teeth (interdigitated)
        spread over the height.
    y_lo, y_hi:
        Vertical span. Callers extend this slightly beyond the slider so the
        buffered strip cuts cleanly at the top and bottom edges.
    kind:
        ``"triangle"`` / ``"chevron"`` or ``"square"`` / ``"interdigitated"``.
        ``"rectangular"`` is accepted and treated as a straight line.
    """
    span = y_hi - y_lo
    n = max(1, n_teeth)

    if amp == 0.0 or kind in ("rectangular",):
        return [(x0, y_lo), (x0, y_hi)]

    if kind in ("triangle", "chevron"):
        # Turning points of the triangle wave sit at t = 0.25 + 0.5k.
        ts: list[float] = [0.0]
        k = 0
        while True:
            t = 0.25 + 0.5 * k
            if t >= n:
                break
            ts.append(t)
            k += 1
        ts.append(float(n))
        return [(x0 + amp * _triangle(t), y_lo + (t / n) * span) for t in ts]

    if kind in ("square", "interdigitated"):
        # n bands alternating left/right; the vertical runs are the teeth flanks
        # and the implicit connections between bands are the horizontal flanks.
        edges = [y_lo + i * span / n for i in range(n + 1)]
        pts: list[Point] = []
        for i in range(n):
            x = x0 + (amp if i % 2 == 0 else -amp)
            pts.append((x, edges[i]))
            pts.append((x, edges[i + 1]))
        return pts

    raise ValueError(f"unknown boundary kind: {kind!r}")
