"""The standalone findings-list panel window (spec §8.3, #24) — the manual-acceptance Qt layer.

An IPC plugin is a separate process with **no docked UI** (§9), so the findings-list panel is a
**standalone window** the toolbar action opens — resolved from the confirmed §9 mechanism, not a
dockable in-app panel. This module renders the pure :mod:`returnpath.kicad_plugin.panel` rows in
a PySide6 window and wires the two interactions selection makes possible:

* **click-to-select** — clicking a finding calls back into the live board's ``add_to_selection``
  primitive (the ``on_select`` callback, wired to
  :func:`returnpath.kicad_plugin.plugin._select_finding`) so KiCad flashes the offending trace;
* **un-waive** — the button on a selected waived row rewrites ``return-path.waivers.toml`` via
  :func:`returnpath.kicad_plugin.panel.unwaive`, so the finding resurfaces on the next run.

PySide6 is imported lazily *inside* the functions: the plugin package must stay importable in CI
(no Qt, no KiCad), exactly as the kipy connection is lazy in :mod:`returnpath.kicad_plugin.plugin`.
The window itself — the Qt event loop and the live selection round-trip — is the manual in-KiCad
acceptance step and is not exercised headlessly; the row/section/un-waive *policy* it renders is
unit-tested in :mod:`returnpath.kicad_plugin.panel`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from ..detector import Finding
from ..engine import CheckResult
from .panel import PanelRow, panel_sections, unwaive


def open_findings_panel(
    result: CheckResult,
    waiver_path: Path,
    on_select: Callable[[Finding], bool],
) -> None:
    """Open the standalone findings-list window for *result* and run it to close (spec §8.3).

    *on_select* flashes a clicked finding's trace on the live board; *waiver_path* is the sidecar
    an un-waive rewrites. Reuses an existing ``QApplication`` when KiCad already runs one, else
    creates one, and blocks on the event loop until the user closes the window.
    """
    from PySide6 import QtWidgets  # lazy: Qt is absent in CI and headless runs

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = _make_window_class()(result, waiver_path, on_select)
    window.show()
    app.exec()


def _make_window_class() -> type:
    """Build the panel window class against a lazily-imported PySide6 (avoids a top-level Qt)."""
    from PySide6 import QtCore, QtGui, QtWidgets

    class FindingsPanelWindow(QtWidgets.QMainWindow):
        """A standalone window listing every finding, waived sectioned, with un-waive (#24)."""

        _ROLE_FINDING = int(QtCore.Qt.ItemDataRole.UserRole)

        def __init__(
            self,
            result: CheckResult,
            waiver_path: Path,
            on_select: Callable[[Finding], bool],
        ) -> None:
            super().__init__()
            self._waiver_path = waiver_path
            self._on_select = on_select
            self.setWindowTitle("Return-Path Findings")
            self.resize(720, 480)

            central = QtWidgets.QWidget()
            layout = QtWidgets.QVBoxLayout(central)

            self._tree = QtWidgets.QTreeWidget()
            self._tree.setHeaderLabels(["#", "finding"])
            self._tree.setColumnWidth(0, 40)
            self._tree.setRootIsDecorated(True)
            self._tree.itemClicked.connect(self._on_item_clicked)
            self._tree.currentItemChanged.connect(self._on_current_changed)
            layout.addWidget(self._tree)

            self._unwaive_button = QtWidgets.QPushButton("Un-waive selected")
            self._unwaive_button.setEnabled(False)
            self._unwaive_button.clicked.connect(self._on_unwaive_clicked)
            self._status = QtWidgets.QLabel("")
            row = QtWidgets.QHBoxLayout()
            row.addWidget(self._unwaive_button)
            row.addWidget(self._status, 1)
            layout.addLayout(row)

            self.setCentralWidget(central)
            self._populate(result)

        # -- rendering -------------------------------------------------------- #
        def _populate(self, result: CheckResult) -> None:
            self._tree.clear()
            active, waived = panel_sections(result.findings)
            active_root = QtWidgets.QTreeWidgetItem([f"Findings ({len(active)})", ""])
            waived_root = QtWidgets.QTreeWidgetItem([f"Waived ({len(waived)})", ""])
            for root, rows in ((active_root, active), (waived_root, waived)):
                self._tree.addTopLevelItem(root)
                for r in rows:
                    root.addChild(self._row_item(r))
                root.setExpanded(True)

        def _row_item(self, row: PanelRow) -> "QtWidgets.QTreeWidgetItem":
            item = QtWidgets.QTreeWidgetItem([str(row.number), row.label])
            item.setForeground(1, QtGui.QBrush(QtGui.QColor(row.color)))
            item.setData(0, self._ROLE_FINDING, row.finding)
            item.setToolTip(1, row.finding.message)
            return item

        # -- interactions ----------------------------------------------------- #
        def _finding_of(self, item: object) -> Finding | None:
            if item is None:
                return None
            data = item.data(0, self._ROLE_FINDING)  # type: ignore[attr-defined]
            return data if isinstance(data, Finding) else None

        def _on_item_clicked(self, item: object, _column: int) -> None:
            finding = self._finding_of(item)
            if finding is None:
                return
            if self._on_select(finding):
                self._status.setText(f"selected trace for {finding.cls} · {finding.net}")
            else:
                self._status.setText(f"no routed trace to flash for {finding.net}")

        def _on_current_changed(self, current: object, _previous: object) -> None:
            finding = self._finding_of(current)
            self._unwaive_button.setEnabled(finding is not None and finding.waived)

        def _on_unwaive_clicked(self) -> None:
            finding = self._finding_of(self._tree.currentItem())
            if finding is None or not finding.waived:
                return
            if unwaive(self._waiver_path, finding.id):
                self._status.setText(
                    f"un-waived {finding.id} — resurfaces on the next run "
                    f"({self._waiver_path.name} updated)"
                )
                self._unwaive_button.setEnabled(False)
                item = self._tree.currentItem()
                if item is not None:
                    item.setText(1, item.text(1) + "  [un-waived, re-run to refresh]")
            else:
                self._status.setText(f"no waiver entry {finding.id} in {self._waiver_path.name}")

    return FindingsPanelWindow


def __getattr__(name: str) -> object:
    """Lazily materialise :class:`FindingsPanelWindow` only when Qt is actually available.

    Keeps ``from returnpath.kicad_plugin.panel_window import ...`` cheap and Qt-free at import
    time (CI has no PySide6); the class is built on first attribute access.
    """
    if name == "FindingsPanelWindow":
        return _make_window_class()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
