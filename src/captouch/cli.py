"""Phase 0 spike CLI: emit a trivial footprint + symbol pair for KiCad validation."""

from __future__ import annotations

import argparse
from pathlib import Path

from .export import footprint, symbol

SPIKE_NAME = "CT_Spike_Pad"

# A simple 6 mm square electrode outline (mm). Real electrode geometry
# (chevron / interdigitated / diamond) arrives with the geometry layer in Phase 1.
SPIKE_POLYGON: list[tuple[float, float]] = [(-3, -3), (3, -3), (3, 3), (-3, 3)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="captouch-spike",
        description="Phase-0 format spike: emit a trivial KiCad footprint + symbol.",
    )
    parser.add_argument(
        "-o",
        "--out",
        type=Path,
        default=Path("examples"),
        help="output directory (default: ./examples)",
    )
    args = parser.parse_args(argv)

    args.out.mkdir(parents=True, exist_ok=True)
    fp_path = args.out / f"{SPIKE_NAME}.kicad_mod"
    sym_path = args.out / f"{SPIKE_NAME}.kicad_sym"

    fp_path.write_text(footprint.footprint_text(SPIKE_NAME, SPIKE_POLYGON), encoding="utf-8")
    sym_path.write_text(symbol.symbol_lib_text(SPIKE_NAME), encoding="utf-8")

    print(f"wrote {fp_path}")
    print(f"wrote {sym_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
