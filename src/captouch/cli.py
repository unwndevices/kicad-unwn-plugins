"""Command-line frontend over the same engine the GUI uses.

``captouch slider``    generates a slider footprint + symbol from flags/presets.
``captouch wheel``     generates a wheel (rotary slider) footprint + symbol.
``captouch trackpad``  generates a mutual-cap XY diamond trackpad footprint + symbol.
``captouch gui``       launches the PySide6 live-preview app (needs the gui extra).
``captouch spike``     emits the Phase-0 format-spike pair (kept as a smoke test).
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from typing import Any

from . import __version__
from .export import footprint, symbol
from .geometry import build_slider, build_trackpad, build_wheel, net_tie_number
from .params import (
    CLIP_MODES,
    DEFAULT_PROFILE,
    DISABLE_AREA_FRACTION,
    FAB_PROFILES,
    MASK_SHAPES,
    SLIDER_PRESETS,
    TRACKPAD_PRESETS,
    WHEEL_PRESETS,
    SliderError,
    SliderParams,
    TrackpadParams,
    WheelParams,
    WidgetParams,
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

    return replace(base, **overrides)


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
    if violations and args.strict:
        _report_fab(violations, args.fab_profile, strict=True)
        return 3

    args.out.mkdir(parents=True, exist_ok=True)
    fp_path = args.out / f"{params.name}.kicad_mod"
    sym_path = args.out / f"{params.name}.kicad_sym"
    fp_path.write_text(footprint.slider_footprint_text(geo), encoding="utf-8")
    sym_path.write_text(symbol.slider_symbol_lib_text(geo), encoding="utf-8")
    _maybe_save_params(args, params)

    minx, miny, maxx, maxy = geo.bounds
    print(f"wrote {fp_path}")
    print(f"wrote {sym_path}")
    print(
        f"  {params.segment_shape} slider: {len(geo.active)} active + "
        f"{len(geo.dummies)} dummy electrodes, "
        f"W={params.width:.2f} A={params.air_gap:.2f} H={params.segment_height:.2f} mm, "
        f"extent {maxx - minx:.2f} x {maxy - miny:.2f} mm"
    )
    _report_support(geo)
    _report_fab(violations, args.fab_profile, strict=False)
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
    p.add_argument(
        "--save-params", type=Path, metavar="FILE", help="also write the resolved params as JSON"
    )
    _add_support_args(p)
    _add_fab_args(p)
    p.set_defaults(func=_slider)


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

    return replace(base, **overrides)


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
    if violations and args.strict:
        _report_fab(violations, args.fab_profile, strict=True)
        return 3

    args.out.mkdir(parents=True, exist_ok=True)
    fp_path = args.out / f"{params.name}.kicad_mod"
    sym_path = args.out / f"{params.name}.kicad_sym"
    fp_path.write_text(footprint.wheel_footprint_text(geo), encoding="utf-8")
    sym_path.write_text(symbol.wheel_symbol_lib_text(geo), encoding="utf-8")
    _maybe_save_params(args, params)

    print(f"wrote {fp_path}")
    print(f"wrote {sym_path}")
    print(
        f"  {params.segment_shape} wheel: {len(geo.electrodes)} electrodes, "
        f"W={params.width:.2f} A={params.air_gap:.2f} ring={params.ring_width:.2f} mm, "
        f"OD={params.outer_diameter:.2f} mm, centre hole "
        f"{params.center_hole_diameter:.2f} mm"
    )
    _report_support(geo)
    _report_fab(violations, args.fab_profile, strict=False)
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
        choices=("rectangular", "chevron", "interdigitated"),
        help="electrode boundary style",
    )
    p.add_argument("--num-segments", type=int, help="electrode count around the ring (>=3)")
    p.add_argument(
        "--segment-width", type=float, help="arc width W at mean radius (mm; derived if unset)"
    )
    p.add_argument("--ring-width", type=float, help="radial ring width (mm)")
    p.add_argument("--air-gap", type=float, help="inter-electrode gap A (mm)")
    p.add_argument("--finger-diameter", type=float, help="finger contact diameter (mm)")
    p.add_argument("--num-fingers", type=int, help="teeth per boundary (chevron/interdigitated)")
    p.add_argument("--tooth-depth", type=float, help="boundary half-amplitude (mm)")
    p.add_argument("--corner-radius", type=float, help="extra ESD convex-corner rounding (mm)")
    p.add_argument("--tip-radius", type=float, help="chevron tooth-tip rounding (mm)")
    p.add_argument("--arc-resolution", type=int, help="circle tessellation: segments per 90deg")
    p.add_argument(
        "--relax-finger-constraint", action="store_true", help="skip the W+2A=finger check"
    )
    p.add_argument(
        "--save-params", type=Path, metavar="FILE", help="also write the resolved params as JSON"
    )
    _add_support_args(p)
    _add_fab_args(p)
    p.set_defaults(func=_wheel)


# --------------------------------------------------------------------------- #
# trackpad
# --------------------------------------------------------------------------- #
def _trackpad_params_from_args(args: argparse.Namespace) -> TrackpadParams:
    """Start from a preset (or defaults) and apply only explicitly-set flags."""
    base = TRACKPAD_PRESETS[args.preset] if args.preset else TrackpadParams()

    overrides: dict[str, Any] = {}
    for flag, field in (
        ("name", "name"),
        ("num_rows", "num_rows"),
        ("num_cols", "num_cols"),
        ("diamond_pitch", "diamond_pitch"),
        ("diamond_gap", "diamond_gap"),
        ("bridge_width", "bridge_width"),
        ("via_drill", "via_drill"),
        ("via_diameter", "via_diameter"),
        ("mask_shape", "mask_shape"),
        ("clip_mode", "clip_mode"),
        ("corner_radius", "corner_radius"),
        ("radius", "radius"),
    ):
        value = getattr(args, flag)
        if value is not None:
            overrides[field] = value

    # The smallest copper fragment a curved mask may leave tracks the chosen fab's
    # finest etchable feature, so a non-rect mask never produces sub-fab slivers.
    overrides["min_feature"] = FAB_PROFILES[args.fab_profile].min_track_width
    overrides.update(_support_overrides(args))

    return replace(base, **overrides)


def _trackpad(args: argparse.Namespace) -> int:
    if args.list_fab_profiles:
        return _list_fab_profiles()
    if args.list_presets:
        for key, p in TRACKPAD_PRESETS.items():
            print(f"{key:10} {p.name}  ({p.num_rows}x{p.num_cols} diamonds)")
        return 0

    try:
        params = _trackpad_params_from_args(args)
        geo = build_trackpad(params)
    except SliderError as exc:  # TrackpadError subclasses SliderError
        print(f"error: {exc}")
        return 2

    violations = check_fab(params, args.fab_profile)
    if violations and args.strict:
        _report_fab(violations, args.fab_profile, strict=True)
        return 3

    args.out.mkdir(parents=True, exist_ok=True)
    fp_path = args.out / f"{params.name}.kicad_mod"
    sym_path = args.out / f"{params.name}.kicad_sym"
    fp_path.write_text(footprint.trackpad_footprint_text(geo), encoding="utf-8")
    sym_path.write_text(symbol.trackpad_symbol_lib_text(geo), encoding="utf-8")
    _maybe_save_params(args, params)

    print(f"wrote {fp_path}")
    print(f"wrote {sym_path}")
    print(
        f"  mutual-cap trackpad: {params.num_rows}x{params.num_cols} diamonds "
        f"({len(geo.rx_nets)} Rx + {len(geo.tx_nets)} Tx, {params.num_nodes} nodes), "
        f"pitch={params.diamond_pitch:.2f} gap={params.diamond_gap:.2f} mm, "
        f"extent {params.width:.2f} x {params.height:.2f} mm"
    )
    _report_partial_channels(geo)
    _report_support(geo)
    _report_fab(violations, args.fab_profile, strict=False)
    return 0


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
    p.add_argument("--num-rows", type=int, help="Rx (sense) rows (>= 2, no upper cap)")
    p.add_argument("--num-cols", type=int, help="Tx (drive) columns (>= 2, no upper cap)")
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
        "--save-params", type=Path, metavar="FILE", help="also write the resolved params as JSON"
    )
    _add_support_args(p)
    _add_fab_args(p)
    p.set_defaults(func=_trackpad)


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
        if isinstance(params, WheelParams):
            wgeo = build_wheel(params)
            fp_text = footprint.wheel_footprint_text(wgeo)
            sym_text = symbol.wheel_symbol_lib_text(wgeo)
        elif isinstance(params, TrackpadParams):
            tgeo = build_trackpad(params)
            fp_text = footprint.trackpad_footprint_text(tgeo)
            sym_text = symbol.trackpad_symbol_lib_text(tgeo)
        else:
            sgeo = build_slider(params)
            fp_text = footprint.slider_footprint_text(sgeo)
            sym_text = symbol.slider_symbol_lib_text(sgeo)
    except SliderError as exc:
        print(f"error: {exc}")
        return 2

    violations = check_fab(params, args.fab_profile)
    if violations and args.strict:
        _report_fab(violations, args.fab_profile, strict=True)
        return 3

    args.out.mkdir(parents=True, exist_ok=True)
    fp_path = args.out / f"{params.name}.kicad_mod"
    sym_path = args.out / f"{params.name}.kicad_sym"
    fp_path.write_text(fp_text, encoding="utf-8")
    sym_path.write_text(sym_text, encoding="utf-8")
    print(f"wrote {fp_path}")
    print(f"wrote {sym_path}")
    _report_fab(violations, args.fab_profile, strict=False)
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
    _add_wheel_parser(sub)
    _add_trackpad_parser(sub)
    _add_from_params_parser(sub)
    _add_gui_parser(sub)
    _add_spike_parser(sub)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
