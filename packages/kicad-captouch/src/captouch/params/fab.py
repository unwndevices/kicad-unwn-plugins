"""Fab-rule guards — check resolved geometry against PCB fab minimums.

The design-constraint validators in :mod:`captouch.params` keep an electrode
*electrically* sensible (the ``W + 2A`` finger rule, diamonds that don't collide,
vias that fit inside a diamond). They do **not** know what a given board house can
actually etch and drill. This module adds that second, *manufacturability* layer:
a :class:`FabRules` profile gives the four numbers every fab publishes — minimum
copper feature width, minimum copper-to-copper clearance, minimum drill, and
minimum annular ring — and :func:`check_fab` derives the tightest such dimension a
widget will produce and reports every one that falls below the profile.

These checks are **advisory by default** (Phase 5 decision): generation still
succeeds and the violations are surfaced as warnings in the CLI and GUI; the CLI's
``--strict`` flag promotes them to a hard failure. They are deliberately separate
from the hard design constraints — you may legitimately want copper finer than a
conservative default profile if you know your fab can do it, so just switch
profiles (or relax) rather than being blocked.

The bundled profiles are **representative starting points**, not a substitute for
your fab's own published capabilities — always confirm against the house you order
from. Numbers are in millimetres.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .keypad import KeypadParams
from .mutual_slider import MutualSliderParams
from .slider import SliderParams
from .trackpad import TrackpadParams
from .wheel import WheelParams

#: Every widget params type the fab guards accept.
_WidgetParams = SliderParams | WheelParams | TrackpadParams | MutualSliderParams | KeypadParams

__all__ = [
    "FabRules",
    "FAB_PROFILES",
    "DEFAULT_PROFILE",
    "FabViolation",
    "check_fab",
    "fab_features",
]

# -- the four dimension kinds a fab profile bounds --------------------------- #
WIDTH = "copper width"
CLEARANCE = "copper clearance"
DRILL = "drill"
ANNULAR = "annular ring"

_SQRT2 = math.sqrt(2.0)


@dataclass(frozen=True)
class FabRules:
    """A board house's minimum manufacturable dimensions (mm).

    Attributes
    ----------
    name:
        Short profile key (matches the :data:`FAB_PROFILES` mapping).
    min_track_width:
        Narrowest copper feature the fab can reliably etch.
    min_clearance:
        Smallest copper-to-copper gap the fab can reliably etch.
    min_drill:
        Smallest finished hole the fab will drill.
    min_annular_ring:
        Minimum copper ring left around a drilled hole, **per side**
        (``(pad_diameter - drill) / 2``).
    description:
        One-line human description shown by ``--list-fab-profiles`` / the GUI.
    """

    name: str
    min_track_width: float
    min_clearance: float
    min_drill: float
    min_annular_ring: float
    description: str = ""

    def limit_for(self, kind: str) -> float:
        """Return the profile minimum for one of the four dimension *kind* tags."""
        return {
            WIDTH: self.min_track_width,
            CLEARANCE: self.min_clearance,
            DRILL: self.min_drill,
            ANNULAR: self.min_annular_ring,
        }[kind]


#: Built-in fab profiles. Representative of common 2-layer capabilities — verify
#: against your own board house before committing a design.
FAB_PROFILES: dict[str, FabRules] = {
    # Conservative generic 2-layer (~6 mil). Safe with virtually any board house.
    "default": FabRules(
        name="default",
        min_track_width=0.15,
        min_clearance=0.15,
        min_drill=0.3,
        min_annular_ring=0.15,
        description="conservative generic 2-layer (~6 mil; safe with any fab)",
    ),
    # JLCPCB 2-layer standard (5 mil track/space, 0.2 mm drill, 0.13 mm annular).
    "jlcpcb": FabRules(
        name="jlcpcb",
        min_track_width=0.127,
        min_clearance=0.127,
        min_drill=0.2,
        min_annular_ring=0.13,
        description="JLCPCB 2-layer standard (~5 mil track/space, 0.2 mm drill)",
    ),
    # OSH Park 2-layer (6 mil track/space, 10 mil drill).
    "oshpark": FabRules(
        name="oshpark",
        min_track_width=0.1524,
        min_clearance=0.1524,
        min_drill=0.254,
        min_annular_ring=0.1524,
        description="OSH Park 2-layer (6 mil track/space, 10 mil drill)",
    ),
}

#: Default profile key when the caller does not pick one.
DEFAULT_PROFILE = "default"


@dataclass(frozen=True)
class FabViolation:
    """One fab-rule breach: a derived dimension below the profile minimum."""

    feature: str  # human label, e.g. "bridge via annular ring"
    kind: str  # one of WIDTH / CLEARANCE / DRILL / ANNULAR
    value: float  # the as-designed dimension (mm)
    limit: float  # the profile minimum for this kind (mm)

    @property
    def message(self) -> str:
        return (
            f"{self.feature} = {self.value:.3f} mm is below the {self.kind} "
            f"minimum {self.limit:.3f} mm"
        )


# A raw, profile-independent fab feature: (label, kind, value-in-mm). The tightest
# copper/drill dimensions a widget produces, derived analytically from its params.
_Feature = tuple[str, str, float]


def _slider_features(p: SliderParams) -> list[_Feature]:
    feats: list[_Feature] = [("inter-electrode gap", CLEARANCE, p.air_gap)]
    # Chevron tooth-tips taper to a point; the tip rounding caps them to a copper
    # feature ~2·r wide (0 → a sharp, unetchable point). Other shapes have no
    # acute tips, so their narrowest feature is governed by the gap above.
    if p.segment_shape == "chevron":
        feats.append(("chevron tip rounding", WIDTH, 2.0 * p.tip_radius))
    return feats


def _wheel_features(p: WheelParams) -> list[_Feature]:
    feats: list[_Feature] = [("inter-electrode gap", CLEARANCE, p.air_gap)]
    if p.segment_shape == "chevron":
        feats.append(("chevron tip rounding", WIDTH, 2.0 * p.tip_radius))
    return feats


def _trackpad_features(p: TrackpadParams) -> list[_Feature]:
    # Facing 45° edges of adjacent diamonds sit `diamond_gap` apart, but the
    # bridge neck threads a `gap·√2`-wide corridor, leaving `(gap·√2 − neck)/2` of
    # copper clearance on each side — the tightest clearance in the whole pattern.
    neck_pinch = (p.diamond_gap * _SQRT2 - p.bridge_width) / 2.0
    annular = (p.via_diameter - p.via_drill) / 2.0
    return [
        ("diamond facing-edge gap", CLEARANCE, p.diamond_gap),
        ("bridge-neck pinch clearance", CLEARANCE, neck_pinch),
        ("bridge neck / strap width", WIDTH, p.bridge_width),
        ("bridge via drill", DRILL, p.via_drill),
        ("bridge via annular ring", ANNULAR, annular),
    ]


def _keypad_features(p: KeypadParams) -> list[_Feature]:
    # Discrete self-cap buttons: the only inter-electrode dimension is the
    # button-to-button separation (one big clearance; no necks, vias, or tips).
    return [("button-to-button gap", CLEARANCE, p.gap)]


def _support_features(p: _WidgetParams) -> list[_Feature]:
    """Fab-critical copper widths from the optional support-copper features.

    Only the enabled features contribute (off → no copper → nothing to check),
    so default-off params produce no extra fab warnings.
    """
    feats: list[_Feature] = []
    if p.ground_hatch:
        feats.append(("ground hatch line width", WIDTH, p.ground_hatch_width))
    if p.guard_ring:
        feats.append(("guard ring width", WIDTH, p.guard_width))
    return feats


def fab_features(params: _WidgetParams) -> list[_Feature]:
    """Return the fab-critical dimensions a widget's *params* will produce.

    Dispatches on the params type. Each tuple is ``(label, kind, value_mm)``.
    """
    if isinstance(params, TrackpadParams):
        base = _trackpad_features(params)
    elif isinstance(params, MutualSliderParams):
        # A mutual slider's tightest features are the trackpad's (it is a 1-row
        # diamond matrix): diamond gap, neck pinch, bridge width, via drill/annular.
        base = _trackpad_features(params.to_trackpad())
    elif isinstance(params, KeypadParams):
        base = _keypad_features(params)
    elif isinstance(params, WheelParams):
        base = _wheel_features(params)
    elif isinstance(params, SliderParams):
        base = _slider_features(params)
    else:
        raise TypeError(f"unsupported params type for fab check: {type(params).__name__}")
    return base + _support_features(params)


def check_fab(
    params: _WidgetParams,
    rules: FabRules | str = DEFAULT_PROFILE,
) -> list[FabViolation]:
    """Check *params* against a fab profile, returning every violation.

    *rules* may be a :class:`FabRules` or a profile key from :data:`FAB_PROFILES`.
    An empty list means the geometry clears the profile. Does not raise on a
    violation — callers decide whether to warn or fail.
    """
    if isinstance(rules, str):
        try:
            rules = FAB_PROFILES[rules]
        except KeyError:
            raise ValueError(
                f"unknown fab profile {rules!r}; choose from {sorted(FAB_PROFILES)}"
            ) from None

    violations: list[FabViolation] = []
    for label, kind, value in fab_features(params):
        limit = rules.limit_for(kind)
        if value < limit:
            violations.append(FabViolation(feature=label, kind=kind, value=value, limit=limit))
    return violations
