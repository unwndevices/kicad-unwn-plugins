#!/usr/bin/env python3
"""KiCad IPC plugin entrypoint (referenced by ``plugin.json``).

KiCad launches this file in the plugin's managed virtualenv, where the
``kicad-returnpath`` package and its dependencies (``requirements.txt``, incl.
``kicad-python``) are installed. It simply hands off to
:func:`returnpath.kicad_plugin.main`.

For a source checkout (the package not pip-installed), it adds the kicad-returnpath
package's ``src`` directory to ``sys.path`` as a fallback so the plugin runs straight
from the tree.
"""

from __future__ import annotations

import sys
from pathlib import Path


def _ensure_importable() -> None:
    try:
        import returnpath  # noqa: F401
    except ModuleNotFoundError:
        # entry.py lives in <repo>/plugins/returnpath/; the package is in
        # <repo>/packages/kicad-returnpath/src/.
        repo = Path(__file__).resolve().parent.parent.parent
        src = repo / "packages" / "kicad-returnpath" / "src"
        if (src / "returnpath").is_dir():
            sys.path.insert(0, str(src))


def main() -> int:
    _ensure_importable()
    from returnpath.kicad_plugin import main as plugin_main

    return plugin_main(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
