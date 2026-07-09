"""Optional overlay / dielectric + board-stack fields feeding sensitivity advisories.

Phase 9 adds **advisory** checks (electrode-vs-overlay sizing, a parasitic-Cp
budget, a recommended series resistor) that need a little context the electrode
geometry alone does not carry: how thick the front panel (overlay) is, what it is
made of, and how far the nearest ground plane sits below the copper. This module
defines those few shared fields — exactly as :mod:`captouch.params.support` defines
the support-copper fields — so every widget params dataclass carries them.

The fields are **inert by default**: ``overlay_thickness`` defaults to ``0.0``
(*"no overlay specified"*), which switches the overlay-dependent advisories off, and
nothing here ever changes the emitted footprint/symbol geometry — they only feed the
advisory channel (:mod:`captouch.params.advisory`). Output therefore stays
byte-identical whether or not an overlay is given.

This module is **pure data** — no KiCad, geometry, or Qt imports. The advisory
*checks* that consume these fields live in :mod:`captouch.params.advisory` (which
imports the concrete widget params), mirroring the
:mod:`~captouch.params.support` / :mod:`~captouch.params.fab` split.
"""

from __future__ import annotations

from typing import Protocol

__all__ = [
    "OVERLAY_ER",
    "BOARD_THICKNESS",
    "SensingParams",
    "has_overlay",
    "validate_sensing",
]


# -- field defaults (single source of truth, referenced by every widget) ----- #
#: Default overlay relative permittivity. ~3.0 ≈ acrylic / PMMA / polycarbonate,
#: the most common plastic front panels (guidelines §5.7 table).
OVERLAY_ER = 3.0
#: Default FR-4 substrate thickness (mm) between the electrode layer and the
#: nearest reference ground — used only for the parasitic-Cp estimate. 1.6 mm is
#: the common 2-layer stack (guidelines §5.9 range 0.5–1.6 mm).
BOARD_THICKNESS = 1.6


class SensingParams(Protocol):
    """Structural type for the sensing/overlay fields every widget params carries.

    Lets the shared helpers below stay type-checked without importing the concrete
    dataclasses (which import *this* module), avoiding a cycle — exactly as
    :class:`captouch.params.support.SupportParams` does. Members are read-only
    (``@property``) so the frozen widget dataclasses satisfy it.
    """

    @property
    def overlay_thickness(self) -> float: ...
    @property
    def overlay_er(self) -> float: ...
    @property
    def board_thickness(self) -> float: ...


def has_overlay(p: SensingParams) -> bool:
    """``True`` if *p* specifies a front-panel overlay (thickness > 0).

    The overlay-dependent advisories (electrode-vs-overlay sizing, the sensitivity
    note) only run when this is true; with no overlay given they stay silent.
    """
    return p.overlay_thickness > 0.0


def validate_sensing(p: SensingParams, error_cls: type[Exception]) -> None:
    """Validate the sensing/overlay fields of *p*, raising *error_cls* on violation.

    ``board_thickness`` is always required (it feeds the Cp estimate even with no
    overlay); the overlay fields are only checked when an overlay is specified, so a
    default (overlay-off) params set is never blocked by an inert ``overlay_er``.
    Messages name the offending field so the GUI can highlight the right control.
    """
    if p.overlay_thickness < 0:
        raise error_cls(f"overlay_thickness must be >= 0 (0 = none), got {p.overlay_thickness}")
    if p.board_thickness <= 0:
        raise error_cls(f"board_thickness must be > 0, got {p.board_thickness}")
    if has_overlay(p) and p.overlay_er < 1.0:
        raise error_cls(f"overlay_er must be >= 1.0 (vacuum/air is the floor), got {p.overlay_er}")
