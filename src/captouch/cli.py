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

from .export import footprint, symbol
from .geometry import build_slider, build_trackpad, build_wheel
from .params import (
    SLIDER_PRESETS,
    TRACKPAD_PRESETS,
    WHEEL_PRESETS,
    SliderError,
    SliderParams,
    TrackpadParams,
    WheelParams,
)

SPIKE_NAME = "CT_Spike_Pad"

# A simple 6 mm square electrode outline (mm) for the format spike.
SPIKE_POLYGON: list[tuple[float, float]] = [(-3, -3), (3, -3), (3, 3), (-3, 3)]


# --------------------------------------------------------------------------- #
# slider
# --------------------------------------------------------------------------- #
def _params_from_args(args: argparse.Namespace) -> SliderParams:
    """Start from a preset (or defaults) and apply only explicitly-set flags."""
    base = SLIDER_PRESETS[args.preset] if args.preset else SliderParams()

    overrides: dict[str, object] = {}
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

    return replace(base, **overrides)


def _slider(args: argparse.Namespace) -> int:
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

    args.out.mkdir(parents=True, exist_ok=True)
    fp_path = args.out / f"{params.name}.kicad_mod"
    sym_path = args.out / f"{params.name}.kicad_sym"
    fp_path.write_text(footprint.slider_footprint_text(geo), encoding="utf-8")
    sym_path.write_text(symbol.slider_symbol_lib_text(geo), encoding="utf-8")

    minx, miny, maxx, maxy = geo.bounds
    print(f"wrote {fp_path}")
    print(f"wrote {sym_path}")
    print(
        f"  {params.segment_shape} slider: {len(geo.active)} active + "
        f"{len(geo.dummies)} dummy electrodes, "
        f"W={params.width:.2f} A={params.air_gap:.2f} H={params.segment_height:.2f} mm, "
        f"extent {maxx - minx:.2f} x {maxy - miny:.2f} mm"
    )
    return 0


def _add_slider_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("slider", help="generate a linear slider footprint + symbol")
    p.add_argument("-o", "--out", type=Path, default=Path("examples"),
                   help="output directory (default: ./examples)")
    p.add_argument("--list-presets", action="store_true", help="list presets and exit")
    p.add_argument("--preset", choices=sorted(SLIDER_PRESETS), help="start from a vendor preset")
    p.add_argument("--name", help="footprint/symbol base name")
    p.add_argument("--shape", dest="shape",
                   choices=("rectangular", "chevron", "interdigitated"),
                   help="electrode edge style")
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
    p.add_argument("--relax-finger-constraint", action="store_true",
                   help="skip the W+2A=finger check")
    p.set_defaults(func=_slider)


# --------------------------------------------------------------------------- #
# wheel
# --------------------------------------------------------------------------- #
def _wheel_params_from_args(args: argparse.Namespace) -> WheelParams:
    """Start from a preset (or defaults) and apply only explicitly-set flags."""
    base = WHEEL_PRESETS[args.preset] if args.preset else WheelParams()

    overrides: dict[str, object] = {}
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

    return replace(base, **overrides)


def _wheel(args: argparse.Namespace) -> int:
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

    args.out.mkdir(parents=True, exist_ok=True)
    fp_path = args.out / f"{params.name}.kicad_mod"
    sym_path = args.out / f"{params.name}.kicad_sym"
    fp_path.write_text(footprint.wheel_footprint_text(geo), encoding="utf-8")
    sym_path.write_text(symbol.wheel_symbol_lib_text(geo), encoding="utf-8")

    print(f"wrote {fp_path}")
    print(f"wrote {sym_path}")
    print(
        f"  {params.segment_shape} wheel: {len(geo.electrodes)} electrodes, "
        f"W={params.width:.2f} A={params.air_gap:.2f} ring={params.ring_width:.2f} mm, "
        f"OD={params.outer_diameter:.2f} mm, centre hole "
        f"{params.center_hole_diameter:.2f} mm"
    )
    return 0


def _add_wheel_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("wheel", help="generate a rotary wheel footprint + symbol")
    p.add_argument("-o", "--out", type=Path, default=Path("examples"),
                   help="output directory (default: ./examples)")
    p.add_argument("--list-presets", action="store_true", help="list presets and exit")
    p.add_argument("--preset", choices=sorted(WHEEL_PRESETS), help="start from a vendor preset")
    p.add_argument("--name", help="footprint/symbol base name")
    p.add_argument("--shape", dest="shape",
                   choices=("rectangular", "chevron", "interdigitated"),
                   help="electrode boundary style")
    p.add_argument("--num-segments", type=int, help="electrode count around the ring (>=3)")
    p.add_argument("--segment-width", type=float, help="arc width W at mean radius (mm; derived if unset)")
    p.add_argument("--ring-width", type=float, help="radial ring width (mm)")
    p.add_argument("--air-gap", type=float, help="inter-electrode gap A (mm)")
    p.add_argument("--finger-diameter", type=float, help="finger contact diameter (mm)")
    p.add_argument("--num-fingers", type=int, help="teeth per boundary (chevron/interdigitated)")
    p.add_argument("--tooth-depth", type=float, help="boundary half-amplitude (mm)")
    p.add_argument("--corner-radius", type=float, help="extra ESD convex-corner rounding (mm)")
    p.add_argument("--tip-radius", type=float, help="chevron tooth-tip rounding (mm)")
    p.add_argument("--arc-resolution", type=int, help="circle tessellation: segments per 90deg")
    p.add_argument("--relax-finger-constraint", action="store_true",
                   help="skip the W+2A=finger check")
    p.set_defaults(func=_wheel)


# --------------------------------------------------------------------------- #
# trackpad
# --------------------------------------------------------------------------- #
def _trackpad_params_from_args(args: argparse.Namespace) -> TrackpadParams:
    """Start from a preset (or defaults) and apply only explicitly-set flags."""
    base = TRACKPAD_PRESETS[args.preset] if args.preset else TrackpadParams()

    overrides: dict[str, object] = {}
    for flag, field in (
        ("name", "name"),
        ("num_rows", "num_rows"),
        ("num_cols", "num_cols"),
        ("diamond_pitch", "diamond_pitch"),
        ("diamond_gap", "diamond_gap"),
        ("bridge_width", "bridge_width"),
        ("via_drill", "via_drill"),
        ("via_diameter", "via_diameter"),
    ):
        value = getattr(args, flag)
        if value is not None:
            overrides[field] = value

    return replace(base, **overrides)


def _trackpad(args: argparse.Namespace) -> int:
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

    args.out.mkdir(parents=True, exist_ok=True)
    fp_path = args.out / f"{params.name}.kicad_mod"
    sym_path = args.out / f"{params.name}.kicad_sym"
    fp_path.write_text(footprint.trackpad_footprint_text(geo), encoding="utf-8")
    sym_path.write_text(symbol.trackpad_symbol_lib_text(geo), encoding="utf-8")

    print(f"wrote {fp_path}")
    print(f"wrote {sym_path}")
    print(
        f"  mutual-cap trackpad: {params.num_rows}x{params.num_cols} diamonds "
        f"({len(geo.rx_nets)} Rx + {len(geo.tx_nets)} Tx, {params.num_nodes} nodes), "
        f"pitch={params.diamond_pitch:.2f} gap={params.diamond_gap:.2f} mm, "
        f"extent {params.width:.2f} x {params.height:.2f} mm"
    )
    return 0


def _add_trackpad_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("trackpad", help="generate a mutual-cap XY diamond trackpad footprint + symbol")
    p.add_argument("-o", "--out", type=Path, default=Path("examples"),
                   help="output directory (default: ./examples)")
    p.add_argument("--list-presets", action="store_true", help="list presets and exit")
    p.add_argument("--preset", choices=sorted(TRACKPAD_PRESETS), help="start from a vendor preset")
    p.add_argument("--name", help="footprint/symbol base name")
    p.add_argument("--num-rows", type=int, help="Rx (sense) rows, 3-16")
    p.add_argument("--num-cols", type=int, help="Tx (drive) columns, 3-16")
    p.add_argument("--diamond-pitch", type=float, help="row/column centre spacing P (mm)")
    p.add_argument("--diamond-gap", type=float, help="copper-to-copper gap A between diamonds (mm)")
    p.add_argument("--bridge-width", type=float, help="F.Cu neck / B.Cu strap width (mm)")
    p.add_argument("--via-drill", type=float, help="bridge via finished hole diameter (mm)")
    p.add_argument("--via-diameter", type=float, help="bridge via outer copper diameter (mm)")
    p.set_defaults(func=_trackpad)


# --------------------------------------------------------------------------- #
# gui
# --------------------------------------------------------------------------- #
def _gui(args: argparse.Namespace) -> int:
    try:
        from .gui import main as gui_main  # lazy: keeps PySide6 optional
    except ImportError as exc:
        print(
            f"error: the GUI needs PySide6 ({exc}). "
            f"Install it with: pip install 'kicad-captouch[gui]'"
        )
        return 2
    return gui_main([])


def _add_gui_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("gui", help="launch the live-preview desktop app")
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
    p.add_argument("-o", "--out", type=Path, default=Path("examples"),
                   help="output directory (default: ./examples)")
    p.set_defaults(func=_spike)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="captouch",
        description="Parametric capacitive-touch footprint generator for KiCad.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    _add_slider_parser(sub)
    _add_wheel_parser(sub)
    _add_trackpad_parser(sub)
    _add_gui_parser(sub)
    _add_spike_parser(sub)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
