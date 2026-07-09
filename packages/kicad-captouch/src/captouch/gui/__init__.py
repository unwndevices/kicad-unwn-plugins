"""PySide6 desktop GUI: parameter panel ↔ live preview ↔ export.

The GUI is a thin shell over the same engine the CLI uses
(:mod:`captouch.params` → :mod:`captouch.geometry` → :mod:`captouch.export`); the
preview renders the *same* geometry the exporters serialise, so it is byte-
faithful to the emitted copper.

PySide6 is an optional dependency (``pip install kicad-captouch[gui]``); importing
this package requires it.
"""

from __future__ import annotations

from .app import MainWindow, main, run

__all__ = ["MainWindow", "run", "main"]
