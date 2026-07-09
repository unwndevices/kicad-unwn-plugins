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
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import engine
from ..export import dxf
from ..export.iqs550 import IQS550ConfigError, render_iqs550_config
from ..geometry import KeypadGeometry, MutualSliderGeometry, TrackpadGeometry, WheelGeometry
from ..geometry._base import GeometryError
from ..kicad_plugin import library
from ..params import (
    DEFAULT_PROFILE,
    DEVICES,
    FAB_PROFILES,
    KeypadParams,
    MutualSliderParams,
    SliderError,
    TrackpadParams,
    WheelParams,
    check_advisories,
    check_fab,
    params_from_json,
    params_to_json,
)
from .keypad_panel import KeypadPanel
from .mutual_slider_panel import MutualSliderPanel
from .panel import ParamPanel
from .preview import LAYERS, PreviewView, WidgetGeometry
from .trackpad_panel import TrackpadPanel
from .wheel_panel import WheelPanel

__all__ = ["MainWindow", "run", "main"]

_OK_STYLE = "color: #8fce8f;"
_ERR_STYLE = "color: #e88; font-weight: 600;"

# Amber-on-dark advisory banner for fab-rule + blocking design warnings.
_FAB_BANNER_STYLE = (
    "QLabel { background: #3a2f1a; color: #f0c674; border: 1px solid #6b5630; "
    "border-radius: 6px; padding: 6px 10px; }"
)

# Quieter blue-on-dark line for informational advisories (series-R, sensitivity).
_ADVICE_STYLE = (
    "QLabel { background: #1c2a38; color: #8fbcdb; border: 1px solid #2f4a63; "
    "border-radius: 6px; padding: 6px 10px; }"
)

# (label, panel factory) per selectable widget type. New widgets are appended
# (keypad index 4) so the existing widget-switcher indices stay stable.
_WIDGETS = (
    ("Slider", ParamPanel),
    ("Wheel", WheelPanel),
    ("Trackpad", TrackpadPanel),
    ("Mutual slider", MutualSliderPanel),
    ("Keypad", KeypadPanel),
)


def _summary(geo: WidgetGeometry) -> str:
    """One-line description of the built geometry for the status bar."""
    if isinstance(geo, MutualSliderGeometry):
        # A 1-row trackpad; geo.params is the mapped TrackpadParams
        # (num_cols = Tx drive electrodes, num_rows = Rx sense rows).
        mp = geo.params
        minx, miny, maxx, maxy = geo.bounds
        rows = "row" if mp.num_rows == 1 else "rows"
        return (
            f"mutual-cap slider — {mp.num_cols} Tx drive × {mp.num_rows} Rx sense {rows} "
            f"({mp.num_nodes} nodes, {mp.num_pins} pins) · pitch {mp.diamond_pitch:.2f} "
            f"gap {mp.diamond_gap:.2f} mm · extent {maxx - minx:.2f} × {maxy - miny:.2f} mm"
        )
    if isinstance(geo, TrackpadGeometry):
        tp = geo.params
        minx, miny, maxx, maxy = geo.bounds
        summary = (
            f"mutual-cap trackpad — {tp.num_rows}×{tp.num_cols} diamonds "
            f"({len(geo.rx_nets)} Rx + {len(geo.tx_nets)} Tx, {tp.num_nodes} nodes) · "
            f"pitch {tp.diamond_pitch:.2f} gap {tp.diamond_gap:.2f} mm · "
            f"extent {maxx - minx:.2f} × {maxy - miny:.2f} mm"
        )
        if tp.device:  # a controller profile is enforcing its channel caps
            summary += f" · {DEVICES[tp.device].channels_note()}"
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
    if isinstance(geo, KeypadGeometry):
        kp = geo.params
        minx, miny, maxx, maxy = geo.bounds
        return (
            f"{kp.button_shape} keypad — {kp.num_rows}×{kp.num_cols} buttons "
            f"({kp.num_buttons} keys, {kp.num_pins} pins) · size {kp.button_size:.2f} "
            f"gap {kp.gap:.2f} mm · extent {maxx - minx:.2f} × {maxy - miny:.2f} mm"
        )
    sp = geo.params
    minx, miny, maxx, maxy = geo.bounds
    return (
        f"{sp.segment_shape} slider — {len(geo.active)} active + {len(geo.dummies)} "
        f"dummy, W={sp.width:.2f} A={sp.air_gap:.2f} H={sp.segment_height:.2f} mm · "
        f"extent {maxx - minx:.2f} × {maxy - miny:.2f} mm"
    )


class _InstallDialog(QDialog):
    """Choose where to install the generated footprint + symbol library.

    Defaults to a project-local ``captouch`` library (the open project's
    directory). The footprint ``.pretty`` and symbol ``.kicad_sym`` are independent
    paths, so they may be sent to different libraries; ticking *global* registers in
    KiCad's user-wide tables instead of the project's, for a personal library shared
    across projects.
    """

    def __init__(self, parent: QWidget, *, project_dir: Path, name: str) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add to KiCad project")
        self._project_dir = project_dir
        self._fp_edited = False
        self._sym_edited = False

        nick = library.DEFAULT_NICKNAME
        self._nick = QLineEdit(nick)
        self._fp = QLineEdit(str(project_dir / f"{nick}.pretty"))
        self._sym = QLineEdit(str(project_dir / f"{nick}.kicad_sym"))
        self._global = QCheckBox("Register for all projects (global library table)")
        self._nick.textChanged.connect(self._on_nick_changed)
        self._fp.textEdited.connect(lambda _: setattr(self, "_fp_edited", True))
        self._sym.textEdited.connect(lambda _: setattr(self, "_sym_edited", True))

        form = QFormLayout()
        form.addRow("Library nickname:", self._nick)
        form.addRow("Footprint library (.pretty):", self._path_row(self._fp, self._browse_fp))
        form.addRow("Symbol library (.kicad_sym):", self._path_row(self._sym, self._browse_sym))
        form.addRow("", self._global)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        hint = QLabel(f"Installs “{name}” so KiCad's Add Footprint / Add Symbol can place it.")
        hint.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(hint)
        layout.addWidget(buttons)

    def _path_row(self, edit: QLineEdit, browse) -> QWidget:
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(edit, 1)
        btn = QPushButton("Browse…")
        btn.clicked.connect(browse)
        h.addWidget(btn)
        return row

    def _on_nick_changed(self, text: str) -> None:
        """Track the nickname in the path defaults until the user edits them."""
        nick = text.strip() or library.DEFAULT_NICKNAME
        if not self._fp_edited:
            self._fp.setText(str(self._project_dir / f"{nick}.pretty"))
        if not self._sym_edited:
            self._sym.setText(str(self._project_dir / f"{nick}.kicad_sym"))

    def _browse_fp(self) -> None:
        start = self._fp.text() or str(self._project_dir)
        chosen = QFileDialog.getExistingDirectory(self, "Footprint library (.pretty)", start)
        if chosen:
            self._fp.setText(chosen)
            self._fp_edited = True

    def _browse_sym(self) -> None:
        start = self._sym.text() or str(self._project_dir)
        chosen, _ = QFileDialog.getSaveFileName(
            self, "Symbol library", start, "KiCad symbol library (*.kicad_sym)"
        )
        if chosen:
            self._sym.setText(chosen)
            self._sym_edited = True

    def target(self) -> library.LibraryTarget:
        """Build the chosen :class:`~captouch.kicad_plugin.library.LibraryTarget`."""
        scope = "global" if self._global.isChecked() else "project"
        return library.make_target(
            nickname=self._nick.text().strip() or library.DEFAULT_NICKNAME,
            fp_dir=Path(self._fp.text()).expanduser(),
            sym_path=Path(self._sym.text()).expanduser(),
            scope=scope,
            project_dir=self._project_dir,
        )


class MainWindow(QMainWindow):
    """Top-level window hosting the parameter panel and the live preview."""

    def __init__(self, *, project_dir: Path | None = None) -> None:
        super().__init__()
        self.setWindowTitle("kicad-captouch")
        # When launched as a KiCad IPC plugin, this is the open board's project
        # directory; it switches on the "Add to KiCad project" install action.
        self._project_dir = Path(project_dir) if project_dir is not None else None
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
        rl.addWidget(self._build_advice_line())
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
        img_btn = QPushButton("Save image…")
        img_btn.clicked.connect(self._on_save_image)
        bar.addWidget(img_btn)
        return bar

    def _build_fab_banner(self) -> QLabel:
        """The amber banner that lists current fab-rule + blocking design warnings."""
        self._fab_banner = QLabel()
        self._fab_banner.setStyleSheet(_FAB_BANNER_STYLE)
        self._fab_banner.setWordWrap(True)
        self._fab_banner.setVisible(False)
        return self._fab_banner

    def _build_advice_line(self) -> QLabel:
        """The quiet blue line for informational advisories (series-R, sensitivity)."""
        self._advice_line = QLabel()
        self._advice_line.setStyleSheet(_ADVICE_STYLE)
        self._advice_line.setWordWrap(True)
        self._advice_line.setVisible(False)
        return self._advice_line

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
        self._dxf_btn = QPushButton("Export DXF…")
        self._dxf_btn.clicked.connect(self._on_export_dxf)
        bar.addWidget(self._dxf_btn)
        # Trackpad-only: the IQS550 sensor-config header (Total Rx/Tx + the per-node
        # Active-channels disable map). Enabled only for a trackpad within the chip's
        # 10 Rx × 15 Tx envelope (see _set_actions_enabled / _iqs550_ready).
        self._iqs550_btn = QPushButton("Export IQS550 config…")
        self._iqs550_btn.setToolTip(
            "Write the Azoteq IQS550 sensor-config C header: Total Rx/Tx plus the "
            "per-node Active-channels disable map. Trackpads within 10 Rx × 15 Tx only."
        )
        self._iqs550_btn.clicked.connect(self._on_export_iqs550)
        bar.addWidget(self._iqs550_btn)
        # Only when running as a KiCad plugin: install straight into the open
        # project's library so KiCad's Add Footprint picker can place the part.
        self._install_btn: QPushButton | None = None
        if self._project_dir is not None:
            self._install_btn = QPushButton("Add to KiCad project…")
            self._install_btn.setDefault(True)
            self._install_btn.clicked.connect(self._on_install)
            bar.addWidget(self._install_btn)
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
            self.panel.show_error(str(exc))  # outline the field(s) the error names
            self._set_actions_enabled(self._geo is not None)
            self._fab_banner.setVisible(False)
            self._advice_line.setVisible(False)
            return

        self.panel.clear_error()
        self._geo = geo
        self.preview.set_geometry(geo)
        self._set_actions_enabled(True)
        self._status.setStyleSheet(_OK_STYLE)
        self._status.setText(_summary(geo))
        self._update_advice(geo)

    def _set_actions_enabled(self, on: bool) -> None:
        """Enable/disable the export + install actions together (valid geometry?)."""
        self._export_btn.setEnabled(on)
        self._dxf_btn.setEnabled(on)
        # The IQS550 config is trackpad-specific and needs a matrix within the chip's
        # envelope, so it stays disabled for other widgets / oversize pads.
        self._iqs550_btn.setEnabled(on and self._iqs550_ready())
        if self._install_btn is not None:
            self._install_btn.setEnabled(on)

    def _iqs550_ready(self) -> bool:
        """True when the current geometry is a trackpad on the IQS550 profile.

        Gated on the explicit ``device == "iqs550"`` selection (the GUI equivalent
        of typing ``--iqs550-config`` on the CLI). A built IQS550 geometry already
        fits the envelope — validation would have rejected an over-cap matrix — so
        no separate size check is needed here.
        """
        return isinstance(self._geo, TrackpadGeometry) and self._geo.params.device == "iqs550"

    def _update_advice(self, geo: WidgetGeometry) -> None:
        """Refresh the warning banner + info line from fab checks and advisories.

        Amber banner: fab violations + blocking design advisories (sizing / Cp);
        quiet blue line: the informational advisories (the series-R recommendation,
        always; the overlay sensitivity note when an overlay is set). Full text of
        each warning is on the banner's tooltip.
        """
        profile = self._fab_profile.currentText()
        violations = check_fab(geo.params, profile)
        advisories = check_advisories(geo.params)
        blocking = [a for a in advisories if a.blocks]
        info = [a for a in advisories if not a.blocks]

        warns = [f"{v.feature} {v.value:.3f} < {v.limit:.3f} mm" for v in violations]
        warns += [a.feature for a in blocking]
        if warns:
            plural = "issue" if len(warns) == 1 else "issues"
            self._fab_banner.setText(
                f"⚠ {len(warns)} design {plural} vs '{profile}': {'; '.join(warns)}"
            )
            self._fab_banner.setToolTip(
                "\n".join([v.message for v in violations] + [a.message for a in blocking])
            )
            self._fab_banner.setVisible(True)
        else:
            self._fab_banner.setVisible(False)

        if info:
            self._advice_line.setText("ⓘ  " + "    ".join(a.message for a in info))
            self._advice_line.setVisible(True)
        else:
            self._advice_line.setVisible(False)

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
        fp_text, sym_text = engine.export_widget(self._geo)
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

    def write_dxf(self, path: Path) -> Path:
        """Write the current geometry as a DXF drawing to *path*.

        Returns the path written. Raises if there is no valid geometry. The DXF
        carries the exact geometry on screen (Y-flipped to a y-up CAD frame).
        """
        if self._geo is None:
            raise RuntimeError("no valid geometry to export")
        return dxf.write_widget_dxf(self._geo, path)

    def _on_export_dxf(self) -> None:
        if self._geo is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export DXF", f"{self._geo.params.name}.dxf", "DXF drawing (*.dxf)"
        )
        if not path:
            return
        try:
            self.write_dxf(Path(path))
        except (OSError, RuntimeError) as exc:
            self._status.setStyleSheet(_ERR_STYLE)
            self._status.setText(f"⚠ could not export DXF: {exc}")
            return
        self._status.setStyleSheet(_OK_STYLE)
        self._status.setText(f"Exported DXF → {path}")

    def write_iqs550_config(self, path: Path) -> Path:
        """Write the current trackpad's IQS550 sensor-config header to *path*.

        Returns the path written. Raises :class:`RuntimeError` if the current
        geometry is not a trackpad, or :class:`IQS550ConfigError` if its matrix
        exceeds the chip's channel envelope.
        """
        if not isinstance(self._geo, TrackpadGeometry):
            raise RuntimeError("the IQS550 config is only available for a trackpad")
        Path(path).write_text(render_iqs550_config(self._geo), encoding="utf-8")
        return Path(path)

    def _on_export_iqs550(self) -> None:
        if not isinstance(self._geo, TrackpadGeometry):
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export IQS550 config",
            f"{self._geo.params.name}_iqs550.h",
            "C header (*.h)",
        )
        if not path:
            return
        try:
            self.write_iqs550_config(Path(path))
        except (OSError, RuntimeError, IQS550ConfigError) as exc:
            self._status.setStyleSheet(_ERR_STYLE)
            self._status.setText(f"⚠ could not export IQS550 config: {exc}")
            return
        disabled = sum(not e for row in self._geo.node_enable_map() for e in row)
        self._status.setStyleSheet(_OK_STYLE)
        self._status.setText(
            f"Exported IQS550 config ({disabled} of {self._geo.params.num_nodes} "
            f"node(s) disabled) → {path}"
        )

    # -- install into a KiCad project (plugin mode) ------------------------- #
    def install_current(self, target: library.LibraryTarget) -> library.InstallResult:
        """Install the on-screen geometry into *target*, updating the status line.

        The written footprint + symbol are byte-identical to the preview (and to a
        standalone export). Raises if there is no valid geometry.
        """
        if self._geo is None:
            raise RuntimeError("no valid geometry to install")
        res = library.install(self._geo, target)
        note = "registered" if res.fp_registered else "already registered"
        self._status.setStyleSheet(_OK_STYLE)
        self._status.setText(
            f"Added {res.fp_id} ({note}) — in the PCB editor press A and pick "
            f"'{res.fp_id}'; the symbol is in library '{res.nickname}'"
        )
        return res

    def _on_install(self) -> None:
        if self._geo is None or self._project_dir is None:
            return
        dlg = _InstallDialog(self, project_dir=self._project_dir, name=self._geo.params.name)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.install_current(dlg.target())
        except (library.LibraryError, OSError, RuntimeError) as exc:
            self._status.setStyleSheet(_ERR_STYLE)
            self._status.setText(f"⚠ could not add to KiCad project: {exc}")

    def _on_save_image(self) -> None:
        if self._geo is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save preview image", "preview.png", "PNG image (*.png);;SVG image (*.svg)"
        )
        if not path:
            return
        try:
            self.preview.save_image(path)
        except (OSError, RuntimeError) as exc:
            self._status.setStyleSheet(_ERR_STYLE)
            self._status.setText(f"⚠ could not save image: {exc}")
            return
        self._status.setStyleSheet(_OK_STYLE)
        self._status.setText(f"Saved image → {path}")

    # -- parameter save / load ---------------------------------------------- #
    @staticmethod
    def _widget_index(p) -> int:
        """Selector index (matching _WIDGETS order) for a params object."""
        if isinstance(p, KeypadParams):
            return 4
        if isinstance(p, MutualSliderParams):
            return 3
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


def run(argv: list[str] | None = None, *, project_dir: Path | None = None) -> int:
    """Create the application (if needed), show the window, and run the loop.

    *project_dir* (set by the KiCad plugin) enables the in-app "Add to KiCad
    project" install action targeting that project's library.
    """
    app = QApplication.instance() or QApplication(argv if argv is not None else sys.argv)
    window = MainWindow(project_dir=project_dir)
    window.show()
    return app.exec()


def main(argv: list[str] | None = None, *, project_dir: Path | None = None) -> int:
    """Console-script entry point."""
    return run(argv, project_dir=project_dir)


if __name__ == "__main__":
    raise SystemExit(main())
