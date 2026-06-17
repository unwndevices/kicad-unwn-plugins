# kicad-captouch

A standalone, vendor-agnostic desktop tool that **parametrically generates capacitive-touch
interface footprints** — sliders, wheels, and XY diamond pads — for KiCad, with a live visual
preview. Each widget is emitted as a ready-to-use **footprint (`.kicad_mod`)** plus a matching
**schematic symbol (`.kicad_sym`)**, written directly as KiCad S-expressions (no dependency on
KiCad's in-flux scripting API).

License: **GPL-3.0-or-later**. See [`docs/plan.md`](docs/plan.md) for the architecture, stack, and
roadmap, and the companion research in [`docs/`](docs).

## Status — Phase 0 (format spike)

Proving the riskiest assumption first: that a hand-emitted footprint + symbol opens cleanly and
round-trips across KiCad 9 and 10. Files are emitted in the **KiCad 9.0** format
(footprint `version 20241229`, symbol lib `version 20241209`), which both 9 and 10 accept.

```sh
# generate the spike artifacts into ./examples
PYTHONPATH=src python3 -m captouch.cli --out examples

# run the round-trip / structure tests (needs pytest)
PYTHONPATH=src python3 -m pytest
```

### Validate in KiCad

The format-acceptance gate must be checked against an installed KiCad:

```sh
kicad-cli fp export svg --output /tmp examples/CT_Spike_Pad.kicad_mod   # renders without error
kicad-cli sym export svg --output /tmp examples/CT_Spike_Pad.kicad_sym
```

…or open `examples/CT_Spike_Pad.kicad_mod` in the Footprint Editor and the `.kicad_sym` in the
Symbol Editor.
