"""The slider GUI shell: parameter panel ↔ live preview, plus export.

``MainWindow`` wires :class:`ParamPanel` to :class:`PreviewView`: every parameter
edit rebuilds the geometry and re-renders. Invalid parameters (a
:class:`SliderError`) are reported in the status bar and leave the last good
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
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..export import footprint, symbol
from ..geometry import SliderGeometry, build_slider
from ..params import SliderError
from .panel import ParamPanel
from .preview import LAYERS, PreviewView

__all__ = ["MainWindow", "run", "main"]

_OK_STYLE = "color: #8fce8f;"
_ERR_STYLE = "color: #e88; font-weight: 600;"


class MainWindow(QMainWindow):
    """Top-level window hosting the parameter panel and the live preview."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("kicad-captouch — slider")
        self._geo: SliderGeometry | None = None

        self.panel = ParamPanel()
        self.preview = PreviewView()

        self.setCentralWidget(self._build_central())
        self._status = QLabel()
        self.statusBar().addWidget(self._status, 1)

        self.panel.changed.connect(self._rebuild)
        self.resize(1100, 620)
        self._rebuild()

    # -- layout ------------------------------------------------------------- #
    def _build_central(self) -> QWidget:
        # Left: scrollable parameter panel.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.panel)
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

    def _build_export_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.addStretch(1)
        self._export_btn = QPushButton("Export footprint + symbol…")
        self._export_btn.clicked.connect(self._on_export)
        bar.addWidget(self._export_btn)
        return bar

    # -- behaviour ---------------------------------------------------------- #
    def _rebuild(self) -> None:
        """Rebuild geometry from the panel; render or report the error."""
        params = self.panel.params()
        try:
            geo = build_slider(params)
        except SliderError as exc:
            self._status.setStyleSheet(_ERR_STYLE)
            self._status.setText(f"⚠ {exc}")
            self._export_btn.setEnabled(self._geo is not None)
            return

        self._geo = geo
        self.preview.set_geometry(geo)
        self._export_btn.setEnabled(True)
        minx, miny, maxx, maxy = geo.bounds
        self._status.setStyleSheet(_OK_STYLE)
        self._status.setText(
            f"{params.segment_shape} slider — {len(geo.active)} active + "
            f"{len(geo.dummies)} dummy, W={params.width:.2f} A={params.air_gap:.2f} "
            f"H={params.segment_height:.2f} mm · extent {maxx - minx:.2f} × "
            f"{maxy - miny:.2f} mm"
        )

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
        fp_path.write_text(footprint.slider_footprint_text(self._geo), encoding="utf-8")
        sym_path.write_text(symbol.slider_symbol_lib_text(self._geo), encoding="utf-8")
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
