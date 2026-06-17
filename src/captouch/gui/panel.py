"""Parameter editor for a :class:`SliderParams`.

A grouped form of widgets, one per slider field. Editing anything emits
:attr:`ParamPanel.changed`; the main window reads :meth:`ParamPanel.params` and
rebuilds the geometry. :meth:`ParamPanel.set_params` loads a value back into the
form (used by the preset menu).

The two optional fields — ``segment_width`` and ``tooth_depth`` — are each backed
by a spin box plus an **Auto** checkbox. When *Auto* is ticked the field is
``None`` and the engine derives it (``W = finger - 2A``; ``tooth = 0.3 W``); the
spin box then shows the derived value, greyed, for reference.

Imports Qt and :mod:`captouch.params` only — no geometry, no exporters.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..params import SLIDER_PRESETS, SliderParams
from ..params.slider import SEGMENT_SHAPES

__all__ = ["ParamPanel"]

_PRESET_PLACEHOLDER = "Load preset…"


class ParamPanel(QWidget):
    """Form bound to a :class:`SliderParams`; emits :attr:`changed` on any edit."""

    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._loading = False  # suppress `changed` while loading programmatically
        self._build()
        self.set_params(SliderParams())

    # -- construction ------------------------------------------------------- #
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        # Preset menu — a one-shot action that loads values into the form.
        self.preset = QComboBox()
        self.preset.addItem(_PRESET_PLACEHOLDER)
        self.preset.addItems(sorted(SLIDER_PRESETS))
        self.preset.activated.connect(self._on_preset)
        preset_box = QGroupBox("Preset")
        pl = QVBoxLayout(preset_box)
        pl.addWidget(self.preset)
        root.addWidget(preset_box)

        # Shape & count.
        self.name = QLineEdit()
        self.shape = QComboBox()
        self.shape.addItems(SEGMENT_SHAPES)
        self.num_segments = self._spin(3, 64, 1)
        shape_box = QGroupBox("Shape && count")
        sf = QFormLayout(shape_box)
        sf.addRow("Name", self.name)
        sf.addRow("Segment shape", self.shape)
        sf.addRow("Active segments", self.num_segments)
        root.addWidget(shape_box)

        # Dimensions.
        self.segment_width, self.segment_width_auto = self._auto_dspin(0.1, 60.0, 0.1)
        self.segment_height = self._dspin(0.1, 100.0, 0.5)
        self.air_gap = self._dspin(0.05, 10.0, 0.05)
        self.finger_diameter = self._dspin(1.0, 40.0, 0.5)
        dim_box = QGroupBox("Dimensions (mm)")
        df = QFormLayout(dim_box)
        df.addRow("Segment width W", self._with_auto(self.segment_width, self.segment_width_auto))
        df.addRow("Segment height H", self.segment_height)
        df.addRow("Air gap A", self.air_gap)
        df.addRow("Finger diameter", self.finger_diameter)
        root.addWidget(dim_box)

        # Teeth (chevron / interdigitated only).
        self.num_fingers = self._spin(1, 64, 1)
        self.tooth_depth, self.tooth_depth_auto = self._auto_dspin(0.0, 30.0, 0.1)
        teeth_box = QGroupBox("Teeth (chevron / interdigitated)")
        tf = QFormLayout(teeth_box)
        tf.addRow("Teeth per boundary", self.num_fingers)
        tf.addRow("Tooth depth", self._with_auto(self.tooth_depth, self.tooth_depth_auto))
        root.addWidget(teeth_box)

        # Ends & relief.
        self.end_dummies = self._spin(0, 2, 1)
        self.corner_radius = self._dspin(0.0, 10.0, 0.1)
        self.relax = QCheckBox("Relax W + 2A = finger constraint")
        self.relax.toggled.connect(self._emit)
        end_box = QGroupBox("Ends && relief")
        ef = QFormLayout(end_box)
        ef.addRow("End dummies / side", self.end_dummies)
        ef.addRow("Corner radius", self.corner_radius)
        ef.addRow(self.relax)
        root.addWidget(end_box)

        root.addStretch(1)

        self.name.textEdited.connect(self._emit)
        self.shape.currentIndexChanged.connect(self._on_shape)

    # -- widget helpers ----------------------------------------------------- #
    def _spin(self, lo: int, hi: int, step: int) -> QSpinBox:
        w = QSpinBox()
        w.setRange(lo, hi)
        w.setSingleStep(step)
        w.valueChanged.connect(self._emit)
        return w

    def _dspin(self, lo: float, hi: float, step: float) -> QDoubleSpinBox:
        w = QDoubleSpinBox()
        w.setRange(lo, hi)
        w.setSingleStep(step)
        w.setDecimals(2)
        w.valueChanged.connect(self._emit)
        return w

    def _auto_dspin(self, lo: float, hi: float, step: float) -> tuple[QDoubleSpinBox, QCheckBox]:
        spin = self._dspin(lo, hi, step)
        auto = QCheckBox("Auto")
        auto.toggled.connect(spin.setDisabled)
        auto.toggled.connect(self._emit)
        return spin, auto

    @staticmethod
    def _with_auto(spin: QDoubleSpinBox, auto: QCheckBox) -> QWidget:
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(spin, 1)
        lay.addWidget(auto)
        return row

    # -- signals ------------------------------------------------------------ #
    def _emit(self, *args) -> None:
        if not self._loading:
            self.changed.emit()

    def _on_shape(self) -> None:
        teeth = self.shape.currentText() != "rectangular"
        self.num_fingers.setEnabled(teeth)
        self.tooth_depth_auto.setEnabled(teeth)
        self.tooth_depth.setEnabled(teeth and not self.tooth_depth_auto.isChecked())
        self._emit()

    def _on_preset(self, index: int) -> None:
        if index <= 0:
            return
        key = self.preset.itemText(index)
        self.set_params(SLIDER_PRESETS[key])
        self.preset.setCurrentIndex(0)  # reset to placeholder; menu is action-only
        self.changed.emit()

    # -- params <-> form ---------------------------------------------------- #
    def params(self) -> SliderParams:
        """Read the form into a (possibly invalid, unvalidated) SliderParams."""
        return SliderParams(
            num_segments=self.num_segments.value(),
            segment_shape=self.shape.currentText(),
            segment_width=None if self.segment_width_auto.isChecked() else self.segment_width.value(),
            segment_height=self.segment_height.value(),
            air_gap=self.air_gap.value(),
            finger_diameter=self.finger_diameter.value(),
            num_fingers=self.num_fingers.value(),
            tooth_depth=None if self.tooth_depth_auto.isChecked() else self.tooth_depth.value(),
            end_dummies=self.end_dummies.value(),
            corner_radius=self.corner_radius.value(),
            relax_finger_constraint=self.relax.isChecked(),
            name=self.name.text() or "CT_Slider",
        )

    def set_params(self, p: SliderParams) -> None:
        """Load *p* into the form without emitting :attr:`changed`."""
        self._loading = True
        try:
            self.name.setText(p.name)
            self.shape.setCurrentText(p.segment_shape)
            self.num_segments.setValue(p.num_segments)
            self.segment_height.setValue(p.segment_height)
            self.air_gap.setValue(p.air_gap)
            self.finger_diameter.setValue(p.finger_diameter)
            self.num_fingers.setValue(p.num_fingers)
            self.end_dummies.setValue(p.end_dummies)
            self.corner_radius.setValue(p.corner_radius)
            self.relax.setChecked(p.relax_finger_constraint)

            # Optional fields: Auto reflects None; spin shows the resolved value.
            self.segment_width_auto.setChecked(p.segment_width is None)
            self.segment_width.setValue(p.width)
            self.tooth_depth_auto.setChecked(p.tooth_depth is None)
            self.tooth_depth.setValue(p.amplitude)

            self._on_shape()  # sync enable-state to the loaded shape
        finally:
            self._loading = False
