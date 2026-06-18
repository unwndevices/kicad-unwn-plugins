"""Frozen-binary entry point for the bundled ``captouch`` executable.

PyInstaller needs a real script to analyse; this just hands off to the same
``captouch.cli.main`` the ``captouch`` console script uses, so the binary behaves
identically to ``python -m captouch.cli`` (including ``captouch gui``).
"""

from __future__ import annotations

import sys

from captouch.cli import main

if __name__ == "__main__":
    sys.exit(main())
