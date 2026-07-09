"""kicad-returnpath — a geometric current-return-path checker for KiCad PCBs.

The walking skeleton wires a complete path from a real ``.kicad_pcb`` to findings
and an exit code: :mod:`returnpath.parser` reads the board (honouring the KiCad-10
name-based schema contract), :mod:`returnpath.detector` runs the split-crossing
check with the both-ends-on-plane predicate, :mod:`returnpath.report` renders the
grouped text report, and :mod:`returnpath.cli` is the ``return-path`` entry point.
"""

__version__ = "0.1.0"
