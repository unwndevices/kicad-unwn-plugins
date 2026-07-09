"""Optional board-level support copper: hatched ground + guard / ESD ring.

The v1 generator emitted electrodes only (``docs/plan.md`` §1: *"no board-level
support copper — the user adds those per their board"*). Phase 8 reverses that,
**but every feature is off by default and individually configurable** so the clean
drop-in electrode part stays the default and the golden files stay byte-identical
when the features are off.

Two opt-in features, shared by every widget (slider / wheel / trackpad) via the
flat fields defined here and validated by :func:`validate_support`:

* **Hatched ground fill** — a meshed ground pour on the *opposite* layer (B.Cu),
  which shields without the capacitive loading of a solid pour (guidelines §5.1).
  Configurable hatch line width and pitch (defaults: Infineon's 7 mil line /
  1.14 mm top-layer pitch) and how far it extends past the electrodes
  (``ground_margin``).
* **Guard / ESD ring** — a grounded ring on the electrode layer (F.Cu), offset
  ``guard_gap`` outward from the electrodes (the electrode-to-ground clearance,
  §5.2), ``guard_width`` wide, with a small ``guard_break`` so it does not form a
  closed loop antenna (§4.6), and optionally mask-free (§4.6: the ESD ring must
  not be covered with solder mask).

Both are realised as KiCad ``zone`` objects inside the footprint and tied to a
single ``GND`` net via one net-tie pad + symbol pin (see
:mod:`captouch.geometry.zones` and the exporters). The geometry of the zones is
built in :mod:`captouch.geometry.zones`; this module is **pure data** — no KiCad,
geometry, or Qt imports.
"""

from __future__ import annotations

from typing import Protocol

__all__ = [
    "GROUND_HATCH_WIDTH",
    "GROUND_HATCH_PITCH",
    "GROUND_MARGIN",
    "GUARD_WIDTH",
    "GUARD_GAP",
    "GUARD_BREAK",
    "SupportParams",
    "has_support",
    "validate_support",
]


class SupportParams(Protocol):
    """Structural type for the support-copper fields every widget params carries.

    Lets the shared helpers below stay type-checked without importing the concrete
    dataclasses (which import *this* module), avoiding a cycle. Members are
    read-only (``@property``) so the frozen widget dataclasses satisfy it.
    """

    @property
    def ground_hatch(self) -> bool: ...
    @property
    def ground_margin(self) -> float: ...
    @property
    def ground_hatch_width(self) -> float: ...
    @property
    def ground_hatch_pitch(self) -> float: ...
    @property
    def guard_ring(self) -> bool: ...
    @property
    def guard_width(self) -> float: ...
    @property
    def guard_gap(self) -> float: ...
    @property
    def guard_break(self) -> float: ...
    @property
    def guard_mask_open(self) -> bool: ...


# -- field defaults (single source of truth, referenced by every widget) ----- #
#: Hatch copper-line width (mm). 0.18 mm = 7 mil — Infineon AN85951 §7.4.10.
GROUND_HATCH_WIDTH = 0.18
#: Hatch centre-to-centre pitch (mm). 1.14 mm = 45 mil top layer — Infineon.
GROUND_HATCH_PITCH = 1.14
#: How far the ground pour extends past the electrode outline (mm).
GROUND_MARGIN = 2.0
#: Guard-ring band width (mm).
GUARD_WIDTH = 0.8
#: Gap from the electrodes to the guard ring (mm) — electrode-to-ground, §5.2.
GUARD_GAP = 2.0
#: Break in the guard ring (mm) so it is not a closed loop antenna — §4.6.
GUARD_BREAK = 0.1


def has_support(p: SupportParams) -> bool:
    """``True`` if *p* enables either support-copper feature."""
    return bool(p.ground_hatch or p.guard_ring)


def validate_support(p: SupportParams, error_cls: type[Exception]) -> None:
    """Validate the support-copper fields of *p*, raising *error_cls* on violation.

    Only the fields of an **enabled** feature are checked — values for a disabled
    feature are inert, so off-by-default output is never blocked by a stray value.
    Messages name the offending field so the GUI can highlight the right control.
    """
    if p.ground_hatch:
        if p.ground_margin < 0:
            raise error_cls(f"ground_margin must be >= 0, got {p.ground_margin}")
        if p.ground_hatch_width <= 0:
            raise error_cls(f"ground_hatch_width must be > 0, got {p.ground_hatch_width}")
        if p.ground_hatch_pitch <= p.ground_hatch_width:
            raise error_cls(
                f"ground_hatch_pitch ({p.ground_hatch_pitch}) must be > "
                f"ground_hatch_width ({p.ground_hatch_width}) so the hatch gap is positive"
            )
    if p.guard_ring:
        if p.guard_width <= 0:
            raise error_cls(f"guard_width must be > 0, got {p.guard_width}")
        if p.guard_gap <= 0:
            raise error_cls(f"guard_gap must be > 0, got {p.guard_gap}")
        if p.guard_break < 0:
            raise error_cls(f"guard_break must be >= 0, got {p.guard_break}")
