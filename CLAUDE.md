# kicad-captouch

Parametric generator for **capacitive-touch interface footprints** (sliders, wheels, XY pads) for KiCad: a standalone desktop GUI with live preview that emits a `.kicad_mod` footprint plus a matching `.kicad_sym` symbol via direct S-expression emission. Python + Shapely + PySide6. License: **GPL-3.0**.

See [`docs/plan.md`](./docs/plan.md) for the architecture, stack, and roadmap, and the companion research docs in [`docs/`](./docs).

> This file is intentionally minimal and will grow as the project does.

## Git etiquette

- **Atomic commits** — one logical, self-contained change per commit; the tree should build and pass tests at every commit.
- **Commit as you go** — land each logical unit as its own commit *while* working through a multi-step task, not batched at the end. Committing incrementally keeps commits naturally atomic and the history reviewable; reconstructing the split afterwards is error-prone and is to be avoided.
- **Clear messages** — imperative mood, optionally scoped (e.g. `geometry: add chevron interdigitation`); explain *why* in the body when it isn't obvious.
- **Squash noise before merge** — fold WIP / `fixup!` / review-fix commits into their parent so history reads as a series of clean, reviewable units.
- **Branch off `main`** — never commit directly to `main`; use short-lived feature branches and keep history linear (rebase over merge-commits).
- **push only when asked** — do not push unprompted.
