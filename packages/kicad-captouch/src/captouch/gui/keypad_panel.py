"""Parameter editor for a :class:`KeypadParams` (discrete self-cap button grid).

The simplest panel: a grid size, a per-button shape and size, and the button-to-
button separation, plus the shared support-copper and overlay groups. Editing
anything emits :attr:`changed`; the main window reads :meth:`params` and rebuilds
via :func:`~captouch.geometry.build_keypad`.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QLineEdit,
    QVBoxLayout,
)

from ..geometry import build_keypad
from ..params import BUTTON_SHAPES, KEYPAD_PRESETS, KeypadParams
from ._panel_base import PRESET_PLACEHOLDER as _PRESET_PLACEHOLDER
from ._panel_base import PanelBase

__all__ = ["KeypadPanel"]


class KeypadPanel(PanelBase):
    """Form bound to a :class:`KeypadParams`; emits :attr:`changed` on any edit."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._build()
        self.set_params(KeypadParams())

    def build_geometry(self):
        """Build the keypad geometry for the current form (may raise KeypadError)."""
        return build_keypad(self.params())

    # -- construction ------------------------------------------------------- #
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        self.preset = QComboBox()
        self.preset.addItem(_PRESET_PLACEHOLDER)
        self.preset.addItems(sorted(KEYPAD_PRESETS))
        self.preset.activated.connect(self._on_preset)
        preset_box = QGroupBox("Preset")
        pl = QVBoxLayout(preset_box)
        pl.addWidget(self.preset)
        root.addWidget(preset_box)

        # Grid.
        self.name = QLineEdit()
        self.num_rows = self._spin(1, 64, 1)
        self.num_cols = self._spin(1, 64, 1)
        grid_box = QGroupBox("Grid")
        gf = QFormLayout(grid_box)
        gf.addRow("Name", self.name)
        gf.addRow("Rows", self.num_rows)
        gf.addRow("Columns", self.num_cols)
        root.addWidget(grid_box)

        # Buttons.
        self.button_shape = QComboBox()
        self.button_shape.addItems(BUTTON_SHAPES)
        self.button_size = self._dspin(2.0, 50.0, 0.5)
        self.gap = self._dspin(0.5, 30.0, 0.5)
        self.corner_radius = self._dspin(0.0, 10.0, 0.1)
        btn_box = QGroupBox("Buttons (mm)")
        bf = QFormLayout(btn_box)
        bf.addRow("Shape", self.button_shape)
        bf.addRow("Size", self.button_size)
        bf.addRow("Separation (gap)", self.gap)
        bf.addRow("Corner radius", self.corner_radius)
        root.addWidget(btn_box)

        # Optional support copper (hatched ground + guard ring), default off.
        root.addWidget(self._build_support_group())

        # Overlay / sensitivity inputs (advisory only; no geometry effect).
        root.addWidget(self._build_sensing_group())

        root.addStretch(1)

        self.name.textEdited.connect(self._emit)
        self.button_shape.currentIndexChanged.connect(self._on_shape_changed)

        self._set_tooltips(
            {
                self.name: "Base name for the generated .kicad_mod / .kicad_sym files.",
                self.num_rows: "Buttons down the grid (Y).",
                self.num_cols: "Buttons across the grid (X).",
                self.button_shape: (
                    "Per-button electrode shape: rect (square), circle (round), or "
                    "diamond (square rotated 45°)."
                ),
                self.button_size: (
                    "Button dimension (mm): square side / circle diameter / diamond diagonal. "
                    "Should be ≥ 3 × the overlay thickness (TI rule)."
                ),
                self.gap: (
                    "Button-to-button edge-to-edge separation (mm). Keep it ≥ 4 mm + overlay "
                    "thickness so a finger on one button does not couple into its neighbour "
                    "(Microchip AN2934 §1.2.2)."
                ),
                self.corner_radius: "ESD corner rounding for rect / diamond (mm); ignored for circle.",
            }
        )
        self._on_shape_changed()  # initial enable state for corner radius

    # -- signals ------------------------------------------------------------ #
    def _on_shape_changed(self, *args) -> None:
        """Corner rounding is meaningless for a circle — disable it there."""
        self.corner_radius.setEnabled(self.button_shape.currentText() != "circle")
        self._emit()

    def _on_preset(self, index: int) -> None:
        if index <= 0:
            return
        key = self.preset.itemText(index)
        self.set_params(KEYPAD_PRESETS[key])
        self.preset.setCurrentIndex(0)  # reset to placeholder; menu is action-only
        self.changed.emit()

    # -- params <-> form ---------------------------------------------------- #
    def params(self) -> KeypadParams:
        """Read the form into a (possibly invalid, unvalidated) KeypadParams."""
        return KeypadParams(
            num_rows=self.num_rows.value(),
            num_cols=self.num_cols.value(),
            button_shape=self.button_shape.currentText(),
            button_size=self.button_size.value(),
            gap=self.gap.value(),
            corner_radius=self.corner_radius.value(),
            name=self.name.text() or "CT_Keypad",
            **self._support_kwargs(),
            **self._sensing_kwargs(),
        )

    def set_params(self, p: KeypadParams) -> None:
        """Load *p* into the form without emitting :attr:`changed`."""
        self._loading = True
        try:
            self.name.setText(p.name)
            self.num_rows.setValue(p.num_rows)
            self.num_cols.setValue(p.num_cols)
            self.button_shape.setCurrentText(p.button_shape)
            self.button_size.setValue(p.button_size)
            self.gap.setValue(p.gap)
            self.corner_radius.setValue(p.corner_radius)
            self._load_support(p)
            self._load_sensing(p)
            self._on_shape_changed()  # corner-radius enable state after load
        finally:
            self._loading = False
