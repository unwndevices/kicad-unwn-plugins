"""Build mutual-cap (CSX) slider geometry from :class:`MutualSliderParams`.

A mutual-cap slider is, geometrically, a diamond trackpad collapsed to a single
sense row (see :mod:`captouch.params.mutual_slider`): one continuous F.Cu Rx line
crossed by ``num_segments`` B.Cu-bridged Tx drive electrodes. So this builder is a
thin façade over :func:`~captouch.geometry.trackpad.build_trackpad` — it validates
the slider-level params, maps them onto a :class:`TrackpadParams`, and runs the
shared diamond/neck/via-bridge engine with ``min_lines=1`` to permit the single
sense row. The result is a :class:`MutualSliderGeometry`, a marker subtype of
:class:`TrackpadGeometry`, so the trackpad footprint exporter, symbol exporter,
live preview, and DRC gate are all reused verbatim while the GUI/CLI can still
recognise (and label) the widget as a 1-D slider.

**No KiCad or Qt imports.** Depends only on the trackpad geometry layer.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..params import MutualSliderParams, validate_mutual_slider
from .trackpad import TrackpadGeometry, build_trackpad

__all__ = ["MutualSliderGeometry", "build_mutual_slider"]


@dataclass(frozen=True)
class MutualSliderGeometry(TrackpadGeometry):
    """A :class:`TrackpadGeometry` built as a 1-D mutual-cap slider.

    Adds no geometry of its own — it is a type marker so the exporters/preview
    (which accept any :class:`TrackpadGeometry`) work unchanged while the GUI/CLI
    can tell a mutual slider apart from a true XY trackpad for labelling.
    """


def build_mutual_slider(params: MutualSliderParams) -> MutualSliderGeometry:
    """Build a :class:`MutualSliderGeometry` from validated *params*.

    Validates the mutual-slider constraints, then delegates to the trackpad engine
    (``min_lines=1`` allows the single continuous sense row).
    """
    validate_mutual_slider(params)
    tg = build_trackpad(params.to_trackpad(), min_lines=1)
    return MutualSliderGeometry(nets=tg.nets, bounds=tg.bounds, params=tg.params)
