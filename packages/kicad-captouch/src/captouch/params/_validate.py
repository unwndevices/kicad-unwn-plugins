"""Shared parameter-validation helpers.

Pure data, no KiCad/geometry/Qt imports — see ``params/__init__.py``.
"""

from __future__ import annotations

import math


def require_finite(p: object, error_cls: type[Exception]) -> None:
    """Raise *error_cls* if any float field of dataclass *p* is NaN or infinite.

    Non-finite values would otherwise flow silently into Shapely (degenerate
    geometry) and the S-expression float formatter (which emits literal
    ``nan`` / ``inf`` tokens, producing a malformed ``.kicad_mod``). Catch them
    at the parameter boundary with a clear message instead. ``None`` (unset
    optional) and ``bool`` fields are ignored; ints are always finite.
    """
    for name, value in vars(p).items():
        if isinstance(value, float) and not math.isfinite(value):
            raise error_cls(f"{name} must be a finite number, got {value!r}")
