"""The in-KiCad IPC plugin for the return-path checker (spec §9).

A thin GUI-only wrapper over the CLI core: it runs the same check on the *live* open
board and surfaces the findings as native DRC markers, a durable ``User.*`` overlay, and
selection (§8.3). The CLI stays the CI path; this package needs a running KiCad.

``surfaces`` holds the pure, tested finding → surface policy; ``plugin`` holds the kipy
connection and drawing (the manual-acceptance path) plus :func:`plugin.main`.
"""

from __future__ import annotations

from .plugin import main

__all__ = ["main"]
