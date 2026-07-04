"""Command-line frontend over the same engine the GUI uses.

``captouch slider``         generates a self-cap slider footprint + symbol.
``captouch mutual-slider``  generates a mutual-cap (CSX) diamond slider footprint + symbol.
``captouch wheel``          generates a wheel (rotary slider) footprint + symbol.
``captouch trackpad``       generates a mutual-cap XY diamond trackpad footprint + symbol.
``captouch keypad``         generates a discrete self-cap button-grid footprint + symbol.
``captouch gui``            launches the PySide6 live-preview app (needs the gui extra).
``captouch spike``          emits the Phase-0 format-spike pair (kept as a smoke test).
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from typing import Any

from . import __version__, engine
from .export import dxf, footprint, iqs550, symbol
from .geometry import (
    build_keypad,
    build_mutual_slider,
    build_slider,
    build_trackpad,
    build_wheel,
    net_tie_number,
)
from .params import (
    BUTTON_SHAPES,
    CLIP_MODES,
    DEFAULT_PROFILE,
    DEVICES,
    DISABLE_AREA_FRACTION,
    FAB_PROFILES,
    KEYPAD_PRESETS,
    MASK_SHAPES,
    MUTUAL_SLIDER_PRESETS,
    SLIDER_PRESETS,
    TRACKPAD_PRESETS,
    WHEEL_PRESETS,
    WHEEL_SEGMENT_SHAPES,
    KeypadParams,
    MutualSliderError,
    MutualSliderParams,
    SliderError,
    SliderParams,
    TrackpadError,
    TrackpadParams,
    WheelError,
    WheelParams,
    WidgetParams,
    check_advisories,
    check_fab,
    params_from_json,
    params_to_json,
)

SPIKE_NAME = "CT_Spike_Pad"

# A simple 6 mm square electrode outline (mm) for the format spike.
SPIKE_POLYGON: list[tuple[float, float]] = [(-3, -3), (3, -3), (3, 3), (-3, 3)]


# --------------------------------------------------------------------------- #
# fab-rule guards (shared across slider / wheel / trackpad)
# --------------------------------------------------------------------------- #
def _add_fab_args(p: argparse.ArgumentParser) -> None:
    """Add the shared fab-rule flags to a widget subparser."""
    p.add_argument(
        "--fab-profile",
        choices=sorted(FAB_PROFILES),
        default=DEFAULT_PROFILE,
        help=f"fab-capability profile to check against (default: {DEFAULT_PROFILE})",
    )
    p.add_argument(
        "--strict",
        action="store_true",
        help="treat fab-rule violations as a hard error (refuse to generate)",
    )
    p.add_argument("--list-fab-profiles", action="store_true", help="list fab profiles and exit")


def _list_fab_profiles() -> int:
    for key in sorted(FAB_PROFILES):
        r = FAB_PROFILES[key]
        print(f"{key:9} {r.description}")
        print(
            f"          track {r.min_track_width} clearance {r.min_clearance} "
            f"drill {r.min_drill} annular {r.min_annular_ring} mm"
        )
    return 0


def _report_fab(violations, profile_key: str, *, strict: bool) -> None:
    """Print the fab-rule *violations* as warnings (or errors under *strict*)."""
    if not violations:
        return
    rules = FAB_PROFILES[profile_key]
    head = "error" if strict else "warning"
    print(
        f"{head}: {len(violations)} fab-rule issue(s) vs the '{rules.name}' profile "
        f"({rules.description}):"
    )
    for v in violations:
        print(f"  - {v.message}")
    if strict:
        print(
            "  refusing to generate under --strict — relax the geometry, pick a "
            "finer --fab-profile, or drop --strict"
        )


# --------------------------------------------------------------------------- #
# sensitivity / filtering advisories (shared across slider / wheel / trackpad)
# --------------------------------------------------------------------------- #
def _add_sensing_args(p: argparse.ArgumentParser) -> None:
    """Add the overlay / board-stack flags that feed the design advisories."""
    g = p.add_argument_group("overlay / sensitivity (advisory only)")
    g.add_argument(
        "--overlay-thickness",
        type=float,
        help="front-panel overlay thickness (mm); enables the overlay sizing + "
        "sensitivity advisories (0/unset = no overlay specified)",
    )
    g.add_argument(
        "--overlay-er",
        type=float,
        help="overlay relative permittivity εr (acrylic ~3, glass ~8; guidelines §5.7)",
    )
    g.add_argument(
        "--board-thickness",
        type=float,
        help="FR-4 substrate thickness (mm) used for the parasitic-Cp estimate (default 1.6)",
    )


def _sensing_overrides(args: argparse.Namespace) -> dict[str, Any]:
    """Collect the overlay / board-stack field overrides from explicitly-set flags."""
    overrides: dict[str, Any] = {}
    for field in ("overlay_thickness", "overlay_er", "board_thickness"):
        value = getattr(args, field)
        if value is not None:
            overrides[field] = value
    return overrides


def _strict_blocks(violations, advisories) -> bool:
    """True if a ``--strict`` run should refuse: any fab issue or blocking advisory."""
    return bool(violations) or any(a.blocks for a in advisories)


def _report_advisories(advisories, *, strict: bool) -> None:
    """Print the design advisories (informational, or errors under *strict*)."""
    if not advisories:
        return
    has_block = any(a.blocks for a in advisories)
    head = "error" if (strict and has_block) else "advisory"
    print(f"{head}: {len(advisories)} design advisory(ies) (guidelines §§5.5/5.7/5.10):")
    for a in advisories:
        tag = " [blocks --strict]" if (strict and a.blocks) else ""
        print(f"  - {a.message}{tag}")
    if strict and has_block:
        print(
            "  refusing to generate under --strict — address the blocking "
            "advisory(ies) above, or drop --strict"
        )


# --------------------------------------------------------------------------- #
# optional support copper (shared across slider / wheel / trackpad)
# --------------------------------------------------------------------------- #
def _add_support_args(p: argparse.ArgumentParser) -> None:
    """Add the opt-in support-copper flags (all default off) to a widget subparser."""
    g = p.add_argument_group("support copper (optional, default off)")
    g.add_argument(
        "--ground-hatch",
        action="store_true",
        help="add a hatched ground pour on the opposite layer (B.Cu)",
    )
    g.add_argument("--ground-margin", type=float, help="ground pour reach past the electrodes (mm)")
    g.add_argument(
        "--hatch-width", type=float, dest="ground_hatch_width", help="ground hatch line width (mm)"
    )
    g.add_argument(
        "--hatch-pitch",
        type=float,
        dest="ground_hatch_pitch",
        help="ground hatch centre-to-centre pitch (mm)",
    )
    g.add_argument(
        "--guard-ring", action="store_true", help="add a grounded guard / ESD ring on F.Cu"
    )
    g.add_argument("--guard-width", type=float, help="guard ring band width (mm)")
    g.add_argument("--guard-gap", type=float, help="gap from the electrodes to the guard ring (mm)")
    g.add_argument("--guard-break", type=float, help="break in the guard ring (mm; not a loop)")
    g.add_argument(
        "--guard-no-mask-open",
        action="store_true",
        help="keep solder mask over the guard ring (default: expose it, per §4.6)",
    )


def _support_overrides(args: argparse.Namespace) -> dict[str, Any]:
    """Collect the support-copper field overrides from explicitly-set flags."""
    overrides: dict[str, Any] = {}
    if args.ground_hatch:
        overrides["ground_hatch"] = True
    if args.guard_ring:
        overrides["guard_ring"] = True
    if args.guard_no_mask_open:
        overrides["guard_mask_open"] = False
    for field in (
        "ground_margin",
        "ground_hatch_width",
        "ground_hatch_pitch",
        "guard_width",
        "guard_gap",
        "guard_break",
    ):
        value = getattr(args, field)
        if value is not None:
            overrides[field] = value
    return overrides


def _report_support(geo) -> None:
    """Describe any support copper that was added (and the net-tie reminder)."""
    p = geo.params
    if not (p.ground_hatch or p.guard_ring):
        return
    bits = []
    if p.ground_hatch:
        bits.append(
            f"hatched ground on B.Cu ({p.ground_hatch_width:.2f} mm line / "
            f"{p.ground_hatch_pitch:.2f} mm pitch)"
        )
    if p.guard_ring:
        mask = "mask-free" if p.guard_mask_open else "mask-covered"
        bits.append(
            f"{mask} guard/ESD ring on F.Cu ({p.guard_width:.2f} mm, {p.guard_gap:.2f} mm gap)"
        )
    tie = net_tie_number(geo)
    print(f"  support copper: {', '.join(bits)}")
    print(f"    tied to the GND pin (pad {tie}); assign the zone net to GND on your board")


def _maybe_save_params(args: argparse.Namespace, params: WidgetParams) -> None:
    """Write the resolved params as JSON if ``--save-params`` was given."""
    path = getattr(args, "save_params", None)
    if path is not None:
        path.write_text(params_to_json(params), encoding="utf-8")
        print(f"wrote {path}")


def _maybe_write_dxf(args: argparse.Namespace, geo) -> None:
    """Write a ``{name}.dxf`` mechanical drawing if ``--dxf`` was given."""
    if getattr(args, "dxf", False):
        path = args.out / f"{geo.params.name}.dxf"
        dxf.write_widget_dxf(geo, path)
        print(f"wrote {path}")


def _maybe_write_iqs550_config(args: argparse.Namespace, geo, text: str | None) -> None:
    """Write the pre-rendered IQS550 config header if ``--iqs550-config`` was given.

    *text* is rendered up front (inside the build ``try``) so a matrix that does
    not fit the chip aborts before any file is written; here it is only flushed to
    disk, alongside a one-line node-disable summary.
    """
    path = getattr(args, "iqs550_config", None)
    if path is None or text is None:
        return
    path.write_text(text, encoding="utf-8")
    disabled = sum(not e for row in geo.node_enable_map() for e in row)
    print(f"wrote {path}")
    print(
        f"  IQS550 config: Total Rx={geo.params.num_rows} Tx={geo.params.num_cols}, "
        f"{disabled} of {geo.params.num_nodes} node(s) disabled in the Active-channels map"
    )


def _add_output_args(p: argparse.ArgumentParser) -> None:
    """Add the shared ``--save-params`` / ``--dxf`` extra-output flags."""
    p.add_argument(
        "--save-params", type=Path, metavar="FILE", help="also write the resolved params as JSON"
    )
    p.add_argument(
        "--dxf",
        action="store_true",
        help="also write a DXF drawing (NAME.dxf) for mechanical / CAD handoff",
    )


# --------------------------------------------------------------------------- #
# slider
# --------------------------------------------------------------------------- #
def _params_from_args(args: argparse.Namespace) -> SliderParams:
    """Start from a preset (or defaults) and apply only explicitly-set flags."""
    base = SLIDER_PRESETS[args.preset] if args.preset else SliderParams()

    overrides: dict[str, Any] = {}
    for flag, field in (
        ("name", "name"),
        ("shape", "segment_shape"),
        ("num_segments", "num_segments"),
        ("segment_width", "segment_width"),
        ("segment_height", "segment_height"),
        ("air_gap", "air_gap"),
        ("finger_diameter", "finger_diameter"),
        ("num_fingers", "num_fingers"),
        ("tooth_depth", "tooth_depth"),
        ("end_dummies", "end_dummies"),
        ("corner_radius", "corner_radius"),
        ("tip_radius", "tip_radius"),
    ):
        value = getattr(args, flag)
        if value is not None:
            overrides[field] = value
    if args.relax_finger_constraint:
        overrides["relax_finger_constraint"] = True
    overrides.update(_support_overrides(args))
    overrides.update(_sensing_overrides(args))

    params = replace(base, **overrides)
    if args.length is not None:
        if args.num_segments is not None:
            raise SliderError("size the slider with --length OR --num-segments, not both")
        params = params.fit_to_length(args.length)
    return params


def _slider(args: argparse.Namespace) -> int:
    if args.list_fab_profiles:
        return _list_fab_profiles()
    if args.list_presets:
        for key, p in SLIDER_PRESETS.items():
            print(f"{key:10} {p.name}  ({p.num_segments} seg, {p.segment_shape})")
        return 0

    try:
        params = _params_from_args(args)
        geo = build_slider(params)
    except SliderError as exc:
        print(f"error: {exc}")
        return 2

    violations = check_fab(params, args.fab_profile)
    advisories = check_advisories(params)
    if args.strict and _strict_blocks(violations, advisories):
        _report_fab(violations, args.fab_profile, strict=True)
        _report_advisories(advisories, strict=True)
        return 3

    args.out.mkdir(parents=True, exist_ok=True)
    fp_path = args.out / f"{params.name}.kicad_mod"
    sym_path = args.out / f"{params.name}.kicad_sym"
    fp_path.write_text(footprint.slider_footprint_text(geo), encoding="utf-8")
    sym_path.write_text(symbol.slider_symbol_lib_text(geo), encoding="utf-8")
    _maybe_save_params(args, params)
    _maybe_write_dxf(args, geo)

    minx, miny, maxx, maxy = geo.bounds
    print(f"wrote {fp_path}")
    print(f"wrote {sym_path}")
    print(
        f"  {params.segment_shape} slider: {len(geo.active)} active + "
        f"{len(geo.dummies)} dummy electrodes, "
        f"W={params.width:.2f} A={params.air_gap:.2f} H={params.segment_height:.2f} mm, "
        f"extent {maxx - minx:.2f} x {maxy - miny:.2f} mm"
    )
    if args.length is not None:
        print(
            f"    sized from length: target {args.length:.2f} mm → "
            f"{params.total_length:.2f} mm ({params.num_segments} segments)"
        )
    _report_support(geo)
    _report_fab(violations, args.fab_profile, strict=False)
    _report_advisories(advisories, strict=False)
    return 0


def _add_slider_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("slider", help="generate a linear slider footprint + symbol")
    p.add_argument(
        "-o",
        "--out",
        type=Path,
        default=Path("examples"),
        help="output directory (default: ./examples)",
    )
    p.add_argument("--list-presets", action="store_true", help="list presets and exit")
    p.add_argument("--preset", choices=sorted(SLIDER_PRESETS), help="start from a vendor preset")
    p.add_argument("--name", help="footprint/symbol base name")
    p.add_argument(
        "--shape",
        dest="shape",
        choices=("rectangular", "chevron", "interdigitated"),
        help="electrode edge style",
    )
    p.add_argument("--num-segments", type=int, help="active electrode count (>=3)")
    p.add_argument(
        "--length",
        type=float,
        help="design from a target overall length (mm) instead of --num-segments: "
        "derives the segment count from the pitch (mutually exclusive with --num-segments)",
    )
    p.add_argument("--segment-width", type=float, help="segment width W (mm; derived if unset)")
    p.add_argument("--segment-height", type=float, help="segment height H (mm)")
    p.add_argument("--air-gap", type=float, help="inter-electrode gap A (mm)")
    p.add_argument("--finger-diameter", type=float, help="finger contact diameter (mm)")
    p.add_argument("--num-fingers", type=int, help="teeth per boundary (chevron/interdigitated)")
    p.add_argument("--tooth-depth", type=float, help="boundary half-amplitude (mm)")
    p.add_argument("--end-dummies", type=int, help="grounded dummy segments per end (0-2)")
    p.add_argument("--corner-radius", type=float, help="extra ESD convex-corner rounding (mm)")
    p.add_argument("--tip-radius", type=float, help="chevron tooth-tip rounding (mm)")
    p.add_argument(
        "--relax-finger-constraint", action="store_true", help="skip the W+2A=finger check"
    )
    _add_output_args(p)
    _add_support_args(p)
    _add_sensing_args(p)
    _add_fab_args(p)
    p.set_defaults(func=_slider)


# --------------------------------------------------------------------------- #
# mutual-cap slider
# --------------------------------------------------------------------------- #
def _mutual_slider_params_from_args(args: argparse.Namespace) -> MutualSliderParams:
    """Start from a preset (or defaults) and apply only explicitly-set flags."""
    base = MUTUAL_SLIDER_PRESETS[args.preset] if args.preset else MutualSliderParams()

    overrides: dict[str, Any] = {}
    for flag, field in (
        ("name", "name"),
        ("num_segments", "num_segments"),
        ("sense_rows", "sense_rows"),
        ("diamond_pitch", "diamond_pitch"),
        ("diamond_gap", "diamond_gap"),
        ("bridge_width", "bridge_width"),
        ("via_drill", "via_drill"),
        ("via_diameter", "via_diameter"),
    ):
        value = getattr(args, flag)
        if value is not None:
            overrides[field] = value
    overrides.update(_support_overrides(args))
    overrides.update(_sensing_overrides(args))

    params = replace(base, **overrides)
    if args.length is not None:
        if args.num_segments is not None:
            raise MutualSliderError("size the slider with --length OR --num-segments, not both")
        params = params.fit_to_length(args.length)
    return params


def _mutual_slider(args: argparse.Namespace) -> int:
    if args.list_fab_profiles:
        return _list_fab_profiles()
    if args.list_presets:
        for key, p in MUTUAL_SLIDER_PRESETS.items():
            rows = "row" if p.sense_rows == 1 else "rows"
            print(f"{key:10} {p.name}  ({p.num_segments} seg, {p.sense_rows} sense {rows})")
        return 0

    try:
        params = _mutual_slider_params_from_args(args)
        geo = build_mutual_slider(params)
    except SliderError as exc:  # MutualSliderError subclasses SliderError
        print(f"error: {exc}")
        return 2

    violations = check_fab(params, args.fab_profile)
    advisories = check_advisories(params)
    if args.strict and _strict_blocks(violations, advisories):
        _report_fab(violations, args.fab_profile, strict=True)
        _report_advisories(advisories, strict=True)
        return 3

    args.out.mkdir(parents=True, exist_ok=True)
    fp_path = args.out / f"{params.name}.kicad_mod"
    sym_path = args.out / f"{params.name}.kicad_sym"
    fp_path.write_text(footprint.mutual_slider_footprint_text(geo), encoding="utf-8")
    sym_path.write_text(symbol.mutual_slider_symbol_lib_text(geo), encoding="utf-8")
    _maybe_save_params(args, params)
    _maybe_write_dxf(args, geo)

    rows = "row" if params.sense_rows == 1 else "rows"
    print(f"wrote {fp_path}")
    print(f"wrote {sym_path}")
    print(
        f"  mutual-cap slider: {params.num_segments} Tx drive electrodes x "
        f"{params.sense_rows} Rx sense {rows} ({params.num_nodes} nodes, {params.num_pins} pins), "
        f"pitch={params.diamond_pitch:.2f} gap={params.diamond_gap:.2f} mm, "
        f"extent {params.total_length:.2f} x {params.height:.2f} mm"
    )
    if args.length is not None:
        print(
            f"    sized from length: target {args.length:.2f} mm -> "
            f"{params.total_length:.2f} mm ({params.num_segments} segments)"
        )
    _report_support(geo)
    _report_fab(violations, args.fab_profile, strict=False)
    _report_advisories(advisories, strict=False)
    return 0


def _add_mutual_slider_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "mutual-slider", help="generate a mutual-cap (CSX) diamond slider footprint + symbol"
    )
    p.add_argument(
        "-o",
        "--out",
        type=Path,
        default=Path("examples"),
        help="output directory (default: ./examples)",
    )
    p.add_argument("--list-presets", action="store_true", help="list presets and exit")
    p.add_argument(
        "--preset", choices=sorted(MUTUAL_SLIDER_PRESETS), help="start from a vendor preset"
    )
    p.add_argument("--name", help="footprint/symbol base name")
    p.add_argument("--num-segments", type=int, help="Tx drive electrodes = position nodes (>=3)")
    p.add_argument(
        "--length",
        type=float,
        help="design from a target overall length (mm) instead of --num-segments: "
        "derives the node count from the pitch (mutually exclusive with --num-segments)",
    )
    p.add_argument(
        "--sense-rows", type=int, help="Rx sense rows (1 = single sense line, 2 = dual-row)"
    )
    p.add_argument("--diamond-pitch", type=float, help="drive-electrode centre spacing P (mm)")
    p.add_argument("--diamond-gap", type=float, help="copper-to-copper gap A between diamonds (mm)")
    p.add_argument("--bridge-width", type=float, help="F.Cu neck / B.Cu strap width (mm)")
    p.add_argument("--via-drill", type=float, help="bridge via finished hole diameter (mm)")
    p.add_argument("--via-diameter", type=float, help="bridge via outer copper diameter (mm)")
    _add_output_args(p)
    _add_support_args(p)
    _add_sensing_args(p)
    _add_fab_args(p)
    p.set_defaults(func=_mutual_slider)


# --------------------------------------------------------------------------- #
# wheel
# --------------------------------------------------------------------------- #
def _wheel_params_from_args(args: argparse.Namespace) -> WheelParams:
    """Start from a preset (or defaults) and apply only explicitly-set flags."""
    base = WHEEL_PRESETS[args.preset] if args.preset else WheelParams()

    overrides: dict[str, Any] = {}
    for flag, field in (
        ("name", "name"),
        ("shape", "segment_shape"),
        ("num_segments", "num_segments"),
        ("segment_width", "segment_width"),
        ("ring_width", "ring_width"),
        ("air_gap", "air_gap"),
        ("finger_diameter", "finger_diameter"),
        ("num_fingers", "num_fingers"),
        ("tooth_depth", "tooth_depth"),
        ("spiral_angle", "spiral_angle"),
        ("corner_radius", "corner_radius"),
        ("tip_radius", "tip_radius"),
        ("arc_resolution", "arc_resolution"),
    ):
        value = getattr(args, flag)
        if value is not None:
            overrides[field] = value
    if args.relax_finger_constraint:
        overrides["relax_finger_constraint"] = True
    overrides.update(_support_overrides(args))
    overrides.update(_sensing_overrides(args))

    params = replace(base, **overrides)
    if args.outer_diameter is not None:
        if args.num_segments is not None:
            raise WheelError("size the wheel with --outer-diameter OR --num-segments, not both")
        params = params.fit_to_diameter(args.outer_diameter)
    return params


def _wheel(args: argparse.Namespace) -> int:
    if args.list_fab_profiles:
        return _list_fab_profiles()
    if args.list_presets:
        for key, p in WHEEL_PRESETS.items():
            print(f"{key:10} {p.name}  ({p.num_segments} seg, {p.segment_shape})")
        return 0

    try:
        params = _wheel_params_from_args(args)
        geo = build_wheel(params)
    except SliderError as exc:  # WheelError subclasses SliderError
        print(f"error: {exc}")
        return 2

    violations = check_fab(params, args.fab_profile)
    advisories = check_advisories(params)
    if args.strict and _strict_blocks(violations, advisories):
        _report_fab(violations, args.fab_profile, strict=True)
        _report_advisories(advisories, strict=True)
        return 3

    args.out.mkdir(parents=True, exist_ok=True)
    fp_path = args.out / f"{params.name}.kicad_mod"
    sym_path = args.out / f"{params.name}.kicad_sym"
    fp_path.write_text(footprint.wheel_footprint_text(geo), encoding="utf-8")
    sym_path.write_text(symbol.wheel_symbol_lib_text(geo), encoding="utf-8")
    _maybe_save_params(args, params)
    _maybe_write_dxf(args, geo)

    print(f"wrote {fp_path}")
    print(f"wrote {sym_path}")
    print(
        f"  {params.segment_shape} wheel: {len(geo.electrodes)} electrodes, "
        f"W={params.width:.2f} A={params.air_gap:.2f} ring={params.ring_width:.2f} mm, "
        f"OD={params.outer_diameter:.2f} mm, centre hole "
        f"{params.center_hole_diameter:.2f} mm"
    )
    if args.outer_diameter is not None:
        print(
            f"    sized from diameter: target {args.outer_diameter:.2f} mm → "
            f"{params.outer_diameter:.2f} mm ({params.num_segments} segments)"
        )
    _report_support(geo)
    _report_fab(violations, args.fab_profile, strict=False)
    _report_advisories(advisories, strict=False)
    return 0


def _add_wheel_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("wheel", help="generate a rotary wheel footprint + symbol")
    p.add_argument(
        "-o",
        "--out",
        type=Path,
        default=Path("examples"),
        help="output directory (default: ./examples)",
    )
    p.add_argument("--list-presets", action="store_true", help="list presets and exit")
    p.add_argument("--preset", choices=sorted(WHEEL_PRESETS), help="start from a vendor preset")
    p.add_argument("--name", help="footprint/symbol base name")
    p.add_argument(
        "--shape",
        dest="shape",
        choices=WHEEL_SEGMENT_SHAPES,
        help="electrode boundary style (spiral = iPod-style swirl, wheel only)",
    )
    p.add_argument("--num-segments", type=int, help="electrode count around the ring (>=3)")
    p.add_argument(
        "--outer-diameter",
        type=float,
        help="design from a target outer diameter (mm) instead of --num-segments: "
        "derives the segment count from the pitch (mutually exclusive with --num-segments)",
    )
    p.add_argument(
        "--segment-width", type=float, help="arc width W at mean radius (mm; derived if unset)"
    )
    p.add_argument("--ring-width", type=float, help="radial ring width (mm)")
    p.add_argument("--air-gap", type=float, help="inter-electrode gap A (mm)")
    p.add_argument("--finger-diameter", type=float, help="finger contact diameter (mm)")
    p.add_argument("--num-fingers", type=int, help="teeth per boundary (chevron/interdigitated)")
    p.add_argument("--tooth-depth", type=float, help="boundary half-amplitude (mm)")
    p.add_argument(
        "--spiral-angle",
        type=float,
        help="spiral boundary twist inner->outer (deg; spiral shape only)",
    )
    p.add_argument("--corner-radius", type=float, help="extra ESD convex-corner rounding (mm)")
    p.add_argument("--tip-radius", type=float, help="chevron tooth-tip rounding (mm)")
    p.add_argument("--arc-resolution", type=int, help="circle tessellation: segments per 90deg")
    p.add_argument(
        "--relax-finger-constraint", action="store_true", help="skip the W+2A=finger check"
    )
    _add_output_args(p)
    _add_support_args(p)
    _add_sensing_args(p)
    _add_fab_args(p)
    p.set_defaults(func=_wheel)


# --------------------------------------------------------------------------- #
# trackpad
# --------------------------------------------------------------------------- #
def _trackpad_params_from_args(args: argparse.Namespace) -> TrackpadParams:
    """Start from a preset (or defaults) and apply only explicitly-set flags.

    Two ways to size the matrix: a row/column count (``--num-rows``/``--num-cols``)
    or an overall outline (``--panel-width``/``--panel-height``), which derives the
    counts from the pitch and trims/insets the lattice to the requested size. The
    two are mutually exclusive.
    """
    base = TRACKPAD_PRESETS[args.preset] if args.preset else TrackpadParams()

    overrides: dict[str, Any] = {}
    for flag, field in (
        ("name", "name"),
        ("diamond_pitch", "diamond_pitch"),
        ("diamond_gap", "diamond_gap"),
        ("bridge_width", "bridge_width"),
        ("via_drill", "via_drill"),
        ("via_diameter", "via_diameter"),
        ("mask_shape", "mask_shape"),
        ("clip_mode", "clip_mode"),
        ("corner_radius", "corner_radius"),
        ("radius", "radius"),
        ("device", "device"),
    ):
        value = getattr(args, flag)
        if value is not None:
            overrides[field] = value

    # The smallest copper fragment a curved mask may leave tracks the chosen fab's
    # finest etchable feature, so a non-rect mask never produces sub-fab slivers.
    overrides["min_feature"] = FAB_PROFILES[args.fab_profile].min_track_width
    overrides.update(_support_overrides(args))
    overrides.update(_sensing_overrides(args))

    if args.panel_width is not None or args.panel_height is not None:
        if args.panel_width is None or args.panel_height is None:
            raise TrackpadError("--panel-width and --panel-height must be given together")
        if args.num_rows is not None or args.num_cols is not None:
            raise TrackpadError(
                "size the pad with --panel-width/--panel-height OR --num-rows/--num-cols, not both"
            )
        pitch = args.diamond_pitch if args.diamond_pitch is not None else base.diamond_pitch
        sized = TrackpadParams.from_size(args.panel_width, args.panel_height, diamond_pitch=pitch)
        overrides.update(
            num_rows=sized.num_rows,
            num_cols=sized.num_cols,
            diamond_pitch=pitch,
            panel_width=sized.panel_width,
            panel_height=sized.panel_height,
        )
        return replace(base, **overrides)

    for flag, field in (("num_rows", "num_rows"), ("num_cols", "num_cols")):
        value = getattr(args, flag)
        if value is not None:
            overrides[field] = value
    return replace(base, **overrides)


def _trackpad(args: argparse.Namespace) -> int:
    if args.list_fab_profiles:
        return _list_fab_profiles()
    if args.list_presets:
        for key, p in TRACKPAD_PRESETS.items():
            dev = f", device={p.device}" if p.device else ""
            print(f"{key:10} {p.name}  ({p.num_rows}x{p.num_cols} diamonds{dev})")
        return 0

    try:
        params = _trackpad_params_from_args(args)
        geo = build_trackpad(params)
        # Render the device config up front so an over-envelope matrix fails before
        # any file is written (IQS550ConfigError is a ValueError, not a SliderError).
        iqs_text = iqs550.render_iqs550_config(geo) if args.iqs550_config else None
    except (SliderError, iqs550.IQS550ConfigError) as exc:  # TrackpadError <: SliderError
        print(f"error: {exc}")
        return 2

    violations = check_fab(params, args.fab_profile)
    advisories = check_advisories(params)
    if args.strict and _strict_blocks(violations, advisories):
        _report_fab(violations, args.fab_profile, strict=True)
        _report_advisories(advisories, strict=True)
        return 3

    args.out.mkdir(parents=True, exist_ok=True)
    fp_path = args.out / f"{params.name}.kicad_mod"
    sym_path = args.out / f"{params.name}.kicad_sym"
    fp_path.write_text(footprint.trackpad_footprint_text(geo), encoding="utf-8")
    sym_path.write_text(symbol.trackpad_symbol_lib_text(geo), encoding="utf-8")
    _maybe_save_params(args, params)
    _maybe_write_dxf(args, geo)
    _maybe_write_iqs550_config(args, geo, iqs_text)

    print(f"wrote {fp_path}")
    print(f"wrote {sym_path}")
    print(
        f"  mutual-cap trackpad: {params.num_rows}x{params.num_cols} diamonds "
        f"({len(geo.rx_nets)} Rx + {len(geo.tx_nets)} Tx, {params.num_nodes} nodes), "
        f"pitch={params.diamond_pitch:.2f} gap={params.diamond_gap:.2f} mm, "
        f"outline {params.width:.2f} x {params.height:.2f} mm"
    )
    if params.device:
        print(f"    device: {DEVICES[params.device].channels_note()}")
    _report_panel(params)
    _report_partial_channels(geo)
    _report_support(geo)
    _report_fab(violations, args.fab_profile, strict=False)
    _report_advisories(advisories, strict=False)
    return 0


def _report_panel(params: TrackpadParams) -> None:
    """When the pad was sized from an overall outline, note the derived lattice."""
    if params.panel_width is None and params.panel_height is None:
        return
    lw, lh = params.lattice_width, params.lattice_height
    if lw > params.width or lh > params.height:
        fit = "lattice trimmed to the outline"
    elif lw < params.width or lh < params.height:
        fit = "empty margin left out to the outline"
    else:
        fit = "exact fit"
    print(
        f"    sized from panel: {params.num_cols}x{params.num_rows} diamonds at "
        f"{params.diamond_pitch:.2f} mm pitch span {lw:.2f} x {lh:.2f} mm ({fit})"
    )


def _report_partial_channels(geo) -> None:
    """Warn about channels a curved mask shrinks below the disable threshold."""
    partials = geo.partial_channels()
    if not partials:
        return
    pct = int(round(DISABLE_AREA_FRACTION * 100))
    print(
        f"  {len(partials)} partial channel(s) under {pct}% of full electrode area "
        f"(Azoteq AZD068 §6 — consider disabling these in firmware):"
    )
    for name, frac in partials:
        print(f"    - {name}: {frac * 100:.0f}% area remaining")


def _add_trackpad_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "trackpad", help="generate a mutual-cap XY diamond trackpad footprint + symbol"
    )
    p.add_argument(
        "-o",
        "--out",
        type=Path,
        default=Path("examples"),
        help="output directory (default: ./examples)",
    )
    p.add_argument("--list-presets", action="store_true", help="list presets and exit")
    p.add_argument("--preset", choices=sorted(TRACKPAD_PRESETS), help="start from a vendor preset")
    p.add_argument("--name", help="footprint/symbol base name")
    p.add_argument(
        "--num-rows", type=int, help="Rx (sense) rows (>= 2; capped by --device if set)"
    )
    p.add_argument(
        "--num-cols", type=int, help="Tx (drive) columns (>= 2; capped by --device if set)"
    )
    p.add_argument(
        "--device",
        choices=sorted(DEVICES),
        help="enforce a touch-controller's channel caps (e.g. iqs550: 10 Rx x 15 Tx)",
    )
    p.add_argument(
        "--panel-width",
        type=float,
        help="design from an overall outline width (mm) instead of --num-cols: "
        "derives the column count from the pitch and trims/insets to this exact size",
    )
    p.add_argument(
        "--panel-height",
        type=float,
        help="overall outline height (mm); pair with --panel-width (mutually "
        "exclusive with --num-rows/--num-cols)",
    )
    p.add_argument("--diamond-pitch", type=float, help="row/column centre spacing P (mm)")
    p.add_argument("--diamond-gap", type=float, help="copper-to-copper gap A between diamonds (mm)")
    p.add_argument("--bridge-width", type=float, help="F.Cu neck / B.Cu strap width (mm)")
    p.add_argument("--via-drill", type=float, help="bridge via finished hole diameter (mm)")
    p.add_argument("--via-diameter", type=float, help="bridge via outer copper diameter (mm)")
    p.add_argument(
        "--mask-shape", choices=MASK_SHAPES, help="outer outline: rect (default), rrect, or circle"
    )
    p.add_argument(
        "--clip-mode",
        choices=CLIP_MODES,
        help="curved-mask diamonds: inscribe (default, kept whole or "
        "dropped) or conform (cut to the curve, Azoteq Fig 6.3)",
    )
    p.add_argument(
        "--corner-radius",
        type=float,
        help="rounded-rect fillet radius (mm; with --mask-shape rrect)",
    )
    p.add_argument(
        "--radius",
        type=float,
        help="circle mask radius (mm; with --mask-shape circle; "
        "default = inscribed 0.5·min(width,height))",
    )
    p.add_argument(
        "--iqs550-config",
        type=Path,
        metavar="FILE",
        help="also write an IQS550 sensor-config C header (Total Rx/Tx + the "
        "per-node Active-channels disable map); requires the matrix to fit 10 Rx x 15 Tx",
    )
    _add_output_args(p)
    _add_support_args(p)
    _add_sensing_args(p)
    _add_fab_args(p)
    p.set_defaults(func=_trackpad)


# --------------------------------------------------------------------------- #
# keypad
# --------------------------------------------------------------------------- #
def _keypad_params_from_args(args: argparse.Namespace) -> KeypadParams:
    """Start from a preset (or defaults) and apply only explicitly-set flags."""
    base = KEYPAD_PRESETS[args.preset] if args.preset else KeypadParams()

    overrides: dict[str, Any] = {}
    for flag, field in (
        ("name", "name"),
        ("num_rows", "num_rows"),
        ("num_cols", "num_cols"),
        ("button_shape", "button_shape"),
        ("button_size", "button_size"),
        ("gap", "gap"),
        ("corner_radius", "corner_radius"),
    ):
        value = getattr(args, flag)
        if value is not None:
            overrides[field] = value
    overrides.update(_support_overrides(args))
    overrides.update(_sensing_overrides(args))
    return replace(base, **overrides)


def _keypad(args: argparse.Namespace) -> int:
    if args.list_fab_profiles:
        return _list_fab_profiles()
    if args.list_presets:
        for key, p in KEYPAD_PRESETS.items():
            print(f"{key:10} {p.name}  ({p.num_rows}x{p.num_cols} {p.button_shape} buttons)")
        return 0

    try:
        params = _keypad_params_from_args(args)
        geo = build_keypad(params)
    except SliderError as exc:  # KeypadError subclasses SliderError
        print(f"error: {exc}")
        return 2

    violations = check_fab(params, args.fab_profile)
    advisories = check_advisories(params)
    if args.strict and _strict_blocks(violations, advisories):
        _report_fab(violations, args.fab_profile, strict=True)
        _report_advisories(advisories, strict=True)
        return 3

    args.out.mkdir(parents=True, exist_ok=True)
    fp_path = args.out / f"{params.name}.kicad_mod"
    sym_path = args.out / f"{params.name}.kicad_sym"
    fp_path.write_text(footprint.keypad_footprint_text(geo), encoding="utf-8")
    sym_path.write_text(symbol.keypad_symbol_lib_text(geo), encoding="utf-8")
    _maybe_save_params(args, params)
    _maybe_write_dxf(args, geo)

    print(f"wrote {fp_path}")
    print(f"wrote {sym_path}")
    print(
        f"  {params.button_shape} keypad: {params.num_rows}x{params.num_cols} buttons "
        f"({params.num_buttons} keys, {params.num_pins} pins), "
        f"size={params.button_size:.2f} gap={params.gap:.2f} mm, "
        f"extent {params.width:.2f} x {params.height:.2f} mm"
    )
    _report_support(geo)
    _report_fab(violations, args.fab_profile, strict=False)
    _report_advisories(advisories, strict=False)
    return 0


def _add_keypad_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("keypad", help="generate a discrete self-cap button grid footprint + symbol")
    p.add_argument(
        "-o",
        "--out",
        type=Path,
        default=Path("examples"),
        help="output directory (default: ./examples)",
    )
    p.add_argument("--list-presets", action="store_true", help="list presets and exit")
    p.add_argument("--preset", choices=sorted(KEYPAD_PRESETS), help="start from a vendor preset")
    p.add_argument("--name", help="footprint/symbol base name")
    p.add_argument("--num-rows", type=int, help="buttons down the grid (>= 1)")
    p.add_argument("--num-cols", type=int, help="buttons across the grid (>= 1)")
    p.add_argument(
        "--button-shape", choices=BUTTON_SHAPES, help="per-button shape: rect / circle / diamond"
    )
    p.add_argument(
        "--button-size",
        type=float,
        help="button dimension (mm): square side / circle diameter / diamond diagonal",
    )
    p.add_argument(
        "--gap",
        type=float,
        help="button-to-button edge-to-edge separation (mm; default 4 = Microchip self-cap rule)",
    )
    p.add_argument("--corner-radius", type=float, help="ESD corner rounding for rect/diamond (mm)")
    _add_output_args(p)
    _add_support_args(p)
    _add_sensing_args(p)
    _add_fab_args(p)
    p.set_defaults(func=_keypad)


# --------------------------------------------------------------------------- #
# from-params: regenerate from a saved JSON parameter set
# --------------------------------------------------------------------------- #
def _from_params(args: argparse.Namespace) -> int:
    try:
        params = params_from_json(args.file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"error: {exc}")
        return 2

    try:
        geo = engine.build_widget(params)
        fp_text, sym_text = engine.export_widget(geo)
    except SliderError as exc:
        print(f"error: {exc}")
        return 2

    violations = check_fab(params, args.fab_profile)
    advisories = check_advisories(params)
    if args.strict and _strict_blocks(violations, advisories):
        _report_fab(violations, args.fab_profile, strict=True)
        _report_advisories(advisories, strict=True)
        return 3

    args.out.mkdir(parents=True, exist_ok=True)
    fp_path = args.out / f"{params.name}.kicad_mod"
    sym_path = args.out / f"{params.name}.kicad_sym"
    fp_path.write_text(fp_text, encoding="utf-8")
    sym_path.write_text(sym_text, encoding="utf-8")
    print(f"wrote {fp_path}")
    print(f"wrote {sym_path}")
    _maybe_write_dxf(args, geo)
    _report_fab(violations, args.fab_profile, strict=False)
    _report_advisories(advisories, strict=False)
    return 0


def _add_from_params_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("from-params", help="regenerate a widget from a saved JSON parameter set")
    p.add_argument("file", type=Path, help="parameter JSON (as written by --save-params)")
    p.add_argument(
        "-o",
        "--out",
        type=Path,
        default=Path("examples"),
        help="output directory (default: ./examples)",
    )
    p.add_argument(
        "--dxf",
        action="store_true",
        help="also write a DXF drawing (NAME.dxf) for mechanical / CAD handoff",
    )
    _add_fab_args(p)
    p.set_defaults(func=_from_params)


# --------------------------------------------------------------------------- #
# gui
# --------------------------------------------------------------------------- #
def _gui(args: argparse.Namespace) -> int:
    try:
        from .gui import main as gui_main  # lazy: keeps PySide6 optional
        from .gui.app import MainWindow
    except ImportError as exc:
        print(
            f"error: the GUI needs PySide6 ({exc}). "
            f"Install it with: pip install 'kicad-captouch[gui]'"
        )
        return 2
    if args.check:
        # Non-blocking smoke test: build the app + window (offscreen-friendly) and
        # exit without entering the event loop. Used to verify a packaged binary.
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
        MainWindow()
        del app
        print("gui ok")
        return 0
    return gui_main([])


def _add_gui_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("gui", help="launch the live-preview desktop app")
    p.add_argument(
        "--check",
        action="store_true",
        help="construct the GUI and exit (smoke test; no window loop)",
    )
    p.set_defaults(func=_gui)


# --------------------------------------------------------------------------- #
# spike (Phase 0)
# --------------------------------------------------------------------------- #
def _spike(args: argparse.Namespace) -> int:
    args.out.mkdir(parents=True, exist_ok=True)
    fp_path = args.out / f"{SPIKE_NAME}.kicad_mod"
    sym_path = args.out / f"{SPIKE_NAME}.kicad_sym"
    fp_path.write_text(footprint.footprint_text(SPIKE_NAME, SPIKE_POLYGON), encoding="utf-8")
    sym_path.write_text(symbol.symbol_lib_text(SPIKE_NAME), encoding="utf-8")
    print(f"wrote {fp_path}")
    print(f"wrote {sym_path}")
    return 0


def _add_spike_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("spike", help="emit the Phase-0 format-spike pair")
    p.add_argument(
        "-o",
        "--out",
        type=Path,
        default=Path("examples"),
        help="output directory (default: ./examples)",
    )
    p.set_defaults(func=_spike)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="captouch",
        description="Parametric capacitive-touch footprint generator for KiCad.",
    )
    parser.add_argument("--version", action="version", version=f"captouch {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    _add_slider_parser(sub)
    _add_mutual_slider_parser(sub)
    _add_wheel_parser(sub)
    _add_trackpad_parser(sub)
    _add_keypad_parser(sub)
    _add_from_params_parser(sub)
    _add_gui_parser(sub)
    _add_spike_parser(sub)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
