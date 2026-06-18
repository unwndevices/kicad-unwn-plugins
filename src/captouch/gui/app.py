"""The widget GUI shell: parameter panel ↔ live preview, plus export.

``MainWindow`` wires the active parameter panel (slider or wheel, chosen by a
widget selector) to :class:`PreviewView`: every parameter edit rebuilds the
geometry and re-renders. Invalid parameters (a :class:`SliderError` /
:class:`WheelError`) are reported in the status bar and leave the last good
preview untouched. Export writes the footprint and symbol with the exact geometry
on screen, so the files match the preview.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..export import footprint, symbol
from ..geometry import TrackpadGeometry, WheelGeometry
from ..geometry._base import GeometryError
from ..params import (
    DEFAULT_PROFILE,
    FAB_PROFILES,
    SliderError,
    TrackpadParams,
    WheelParams,
    check_fab,
    params_from_json,
    params_to_json,
)
from .panel import ParamPanel
from .preview import LAYERS, PreviewView, WidgetGeometry
from .trackpad_panel import TrackpadPanel
from .wheel_panel import WheelPanel

__all__ = ["MainWindow", "run", "main"]

_OK_STYLE = "color: #8fce8f;"
_ERR_STYLE = "color: #e88; font-weight: 600;"

# Amber-on-dark advisory banner for fab-rule warnings (non-blocking).
_FAB_BANNER_STYLE = (
    "QLabel { background: #3a2f1a; color: #f0c674; border: 1px solid #6b5630; "
    "border-radius: 6px; padding: 6px 10px; }"
)

# (label, panel factory) per selectable widget type.
_WIDGETS = (("Slider", ParamPanel), ("Wheel", WheelPanel), ("Trackpad", TrackpadPanel))


def _summary(geo: WidgetGeometry) -> str:
    """One-line description of the built geometry for the status bar."""
    if isinstance(geo, TrackpadGeometry):
        tp = geo.params
        minx, miny, maxx, maxy = geo.bounds
        summary = (
            f"mutual-cap trackpad — {tp.num_rows}×{tp.num_cols} diamonds "
            f"({len(geo.rx_nets)} Rx + {len(geo.tx_nets)} Tx, {tp.num_nodes} nodes) · "
            f"pitch {tp.diamond_pitch:.2f} gap {tp.diamond_gap:.2f} mm · "
            f"extent {maxx - minx:.2f} × {maxy - miny:.2f} mm"
        )
        partials = geo.partial_channels()
        if partials:  # a curved mask shrank some edge channels (Azoteq AZD068 §6)
            names = ", ".join(name for name, _ in partials)
            summary += f" · {len(partials)} partial ch <50%: {names} (disable in fw)"
        return summary
    if isinstance(geo, WheelGeometry):
        wp = geo.params
        return (
            f"{wp.segment_shape} wheel — {len(geo.electrodes)} electrodes, "
            f"W={wp.width:.2f} A={wp.air_gap:.2f} ring={wp.ring_width:.2f} mm · "
            f"OD {wp.outer_diameter:.2f} mm, centre hole {wp.center_hole_diameter:.2f} mm"
        )
    sp = geo.params
    minx, miny, maxx, maxy = geo.bounds
    return (
        f"{sp.segment_shape} slider — {len(geo.active)} active + {len(geo.dummies)} "
        f"dummy, W={sp.width:.2f} A={sp.air_gap:.2f} H={sp.segment_height:.2f} mm · "
        f"extent {maxx - minx:.2f} × {maxy - miny:.2f} mm"
    )


class MainWindow(QMainWindow):
    """Top-level window hosting the parameter panel and the live preview."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("kicad-captouch")
        self._geo: WidgetGeometry | None = None

        self._panels = [factory() for _, factory in _WIDGETS]
        self.preview = PreviewView()

        self.setCentralWidget(self._build_central())
        self._status = QLabel()
        self.statusBar().addWidget(self._status, 1)

        for panel in self._panels:
            panel.changed.connect(self._rebuild)
        self.resize(1100, 620)
        self._rebuild()

    @property
    def panel(self):
        """The parameter panel for the currently-selected widget type."""
        return self._stack.currentWidget()

    # -- layout ------------------------------------------------------------- #
    def _build_central(self) -> QWidget:
        # Left: widget selector + the stacked parameter panels, scrollable.
        self._stack = QStackedWidget()
        for panel in self._panels:
            self._stack.addWidget(panel)

        selector = QComboBox()
        selector.addItems([label for label, _ in _WIDGETS])
        selector.currentIndexChanged.connect(self._on_widget_changed)
        self._selector = selector  # kept so Load-params can switch the active widget

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(12, 12, 12, 0)
        ll.setSpacing(6)
        ll.addWidget(QLabel("Widget"))
        ll.addWidget(selector)
        ll.addWidget(self._stack, 1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(left)
        scroll.setMinimumWidth(340)
        scroll.setMaximumWidth(420)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        # Right: layer toggles, preview, export buttons.
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(8, 8, 8, 8)
        rl.setSpacing(8)
        rl.addLayout(self._build_layer_bar())
        rl.addWidget(self.preview, 1)
        rl.addWidget(self._build_fab_banner())
        rl.addLayout(self._build_export_bar())

        central = QWidget()
        cl = QHBoxLayout(central)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addWidget(scroll)
        cl.addWidget(right, 1)
        return central

    def _build_layer_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setSpacing(12)
        bar.addWidget(QLabel("Layers:"))
        for name, label in LAYERS:
            cb = QCheckBox(label)
            cb.setChecked(self.preview.is_layer_visible(name))
            cb.toggled.connect(lambda on, n=name: self.preview.set_layer_visible(n, on))
            bar.addWidget(cb)
        bar.addStretch(1)
        fit = QPushButton("Fit")
        fit.clicked.connect(self.preview.fit)
        bar.addWidget(fit)
        return bar

    def _build_fab_banner(self) -> QLabel:
        """The non-blocking amber banner that lists current fab-rule warnings."""
        self._fab_banner = QLabel()
        self._fab_banner.setStyleSheet(_FAB_BANNER_STYLE)
        self._fab_banner.setWordWrap(True)
        self._fab_banner.setVisible(False)
        return self._fab_banner

    def _build_export_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Fab profile:"))
        self._fab_profile = QComboBox()
        for key in sorted(FAB_PROFILES):
            self._fab_profile.addItem(key)
            self._fab_profile.setItemData(
                self._fab_profile.count() - 1,
                FAB_PROFILES[key].description,
                Qt.ItemDataRole.ToolTipRole,
            )
        self._fab_profile.setCurrentText(DEFAULT_PROFILE)
        self._fab_profile.currentIndexChanged.connect(self._rebuild)
        bar.addWidget(self._fab_profile)
        bar.addStretch(1)
        load_btn = QPushButton("Load params…")
        load_btn.clicked.connect(self._on_load_params)
        bar.addWidget(load_btn)
        save_btn = QPushButton("Save params…")
        save_btn.clicked.connect(self._on_save_params)
        bar.addWidget(save_btn)
        self._export_btn = QPushButton("Export footprint + symbol…")
        self._export_btn.clicked.connect(self._on_export)
        bar.addWidget(self._export_btn)
        return bar

    # -- behaviour ---------------------------------------------------------- #
    def _on_widget_changed(self, index: int) -> None:
        self._stack.setCurrentIndex(index)
        self._rebuild()
        self.preview.fit()  # the new widget's extent is usually very different

    def _rebuild(self) -> None:
        """Rebuild geometry from the active panel; render or report the error."""
        try:
            geo = self.panel.build_geometry()  # WheelError subclasses SliderError
        except (SliderError, GeometryError) as exc:
            self._status.setStyleSheet(_ERR_STYLE)
            self._status.setText(f"⚠ {exc}")
            self._export_btn.setEnabled(self._geo is not None)
            self._fab_banner.setVisible(False)
            return

        self._geo = geo
        self.preview.set_geometry(geo)
        self._export_btn.setEnabled(True)
        self._status.setStyleSheet(_OK_STYLE)
        self._status.setText(_summary(geo))
        self._update_fab_banner(geo)

    def _update_fab_banner(self, geo: WidgetGeometry) -> None:
        """Re-check the geometry against the selected fab profile and show issues."""
        profile = self._fab_profile.currentText()
        violations = check_fab(geo.params, profile)
        if not violations:
            self._fab_banner.setVisible(False)
            return
        items = "; ".join(f"{v.feature} {v.value:.3f} < {v.limit:.3f} mm" for v in violations)
        plural = "issue" if len(violations) == 1 else "issues"
        self._fab_banner.setText(f"⚠ {len(violations)} fab {plural} vs '{profile}': {items}")
        self._fab_banner.setVisible(True)

    def export_to(self, directory: Path) -> tuple[Path, Path]:
        """Write the current geometry's footprint + symbol into *directory*.

        Returns the two written paths. Raises if there is no valid geometry.
        """
        if self._geo is None:
            raise RuntimeError("no valid geometry to export")
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        name = self._geo.params.name
        fp_path = directory / f"{name}.kicad_mod"
        sym_path = directory / f"{name}.kicad_sym"
        if isinstance(self._geo, TrackpadGeometry):
            fp_text = footprint.trackpad_footprint_text(self._geo)
            sym_text = symbol.trackpad_symbol_lib_text(self._geo)
        else:
            fp_text = footprint.widget_footprint_text(self._geo)
            sym_text = symbol.widget_symbol_lib_text(self._geo)
        fp_path.write_text(fp_text, encoding="utf-8")
        sym_path.write_text(sym_text, encoding="utf-8")
        return fp_path, sym_path

    def _on_export(self) -> None:
        if self._geo is None:
            return
        directory = QFileDialog.getExistingDirectory(self, "Export to directory")
        if not directory:
            return
        fp_path, sym_path = self.export_to(Path(directory))
        self._status.setStyleSheet(_OK_STYLE)
        self._status.setText(f"Exported {fp_path.name} and {sym_path.name} → {directory}")

    # -- parameter save / load ---------------------------------------------- #
    @staticmethod
    def _widget_index(p) -> int:
        """Selector index (matching _WIDGETS order) for a params object."""
        if isinstance(p, TrackpadParams):
            return 2
        if isinstance(p, WheelParams):
            return 1
        return 0

    def _on_save_params(self) -> None:
        p = self.panel.params()
        path, _ = QFileDialog.getSaveFileName(
            self, "Save parameters", f"{p.name}.json", "JSON (*.json)"
        )
        if not path:
            return
        Path(path).write_text(params_to_json(p), encoding="utf-8")
        self._status.setStyleSheet(_OK_STYLE)
        self._status.setText(f"Saved parameters → {path}")

    def load_params(self, p) -> None:
        """Switch to *p*'s widget, load it into that panel, and rebuild."""
        self._selector.setCurrentIndex(self._widget_index(p))  # switches the active panel
        self.panel.set_params(p)
        self._rebuild()

    def _on_load_params(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Load parameters", "", "JSON (*.json)")
        if not path:
            return
        try:
            p = params_from_json(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            self._status.setStyleSheet(_ERR_STYLE)
            self._status.setText(f"⚠ could not load parameters: {exc}")
            return
        self.load_params(p)


def run(argv: list[str] | None = None) -> int:
    """Create the application (if needed), show the window, and run the loop."""
    app = QApplication.instance() or QApplication(argv if argv is not None else sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


def main(argv: list[str] | None = None) -> int:
    """Console-script entry point."""
    return run(argv)


if __name__ == "__main__":
    raise SystemExit(main())
