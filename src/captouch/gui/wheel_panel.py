"""Parameter editor for a :class:`WheelParams` (rotary slider).

Mirrors :class:`captouch.gui.panel.ParamPanel` but for the wheel's fields: the
mean radius is derived from the pitch, so the user sets ``ring_width`` (radial
extent) and the same ``W`` / ``A`` / finger rules as the slider, plus an
``arc_resolution`` knob for circle tessellation. Continuous ring → no end
dummies. Editing anything emits :attr:`changed`.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QLineEdit,
    QVBoxLayout,
)

from ..geometry import build_wheel
from ..params import WHEEL_PRESETS, WheelParams
from ..params.slider import SEGMENT_SHAPES
from ._panel_base import PRESET_PLACEHOLDER as _PRESET_PLACEHOLDER
from ._panel_base import PanelBase

__all__ = ["WheelPanel"]


class WheelPanel(PanelBase):
    """Form bound to a :class:`WheelParams`; emits :attr:`changed` on any edit."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._build()
        self.set_params(WheelParams())

    def build_geometry(self):
        """Build the wheel geometry for the current form (may raise WheelError)."""
        return build_wheel(self.params())

    # -- construction ------------------------------------------------------- #
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        self.preset = QComboBox()
        self.preset.addItem(_PRESET_PLACEHOLDER)
        self.preset.addItems(sorted(WHEEL_PRESETS))
        self.preset.activated.connect(self._on_preset)
        preset_box = QGroupBox("Preset")
        pl = QVBoxLayout(preset_box)
        pl.addWidget(self.preset)
        root.addWidget(preset_box)

        # Shape & count.
        self.name = QLineEdit()
        self.shape = QComboBox()
        self.shape.addItems(SEGMENT_SHAPES)
        self.num_segments = self._spin(3, 32, 1)
        shape_box = QGroupBox("Shape && count")
        sf = QFormLayout(shape_box)
        sf.addRow("Name", self.name)
        sf.addRow("Boundary shape", self.shape)
        sf.addRow("Segments", self.num_segments)
        root.addWidget(shape_box)

        # Dimensions.
        self.segment_width, self.segment_width_auto = self._auto_dspin(0.1, 60.0, 0.1)
        self.ring_width = self._dspin(0.5, 40.0, 0.5)
        self.air_gap = self._dspin(0.05, 10.0, 0.05)
        self.finger_diameter = self._dspin(1.0, 40.0, 0.5)
        dim_box = QGroupBox("Dimensions (mm)")
        df = QFormLayout(dim_box)
        df.addRow("Arc width W", self._with_auto(self.segment_width, self.segment_width_auto))
        df.addRow("Ring width", self.ring_width)
        df.addRow("Air gap A", self.air_gap)
        df.addRow("Finger diameter", self.finger_diameter)
        root.addWidget(dim_box)

        # Teeth.
        self.num_fingers = self._spin(1, 32, 1)
        self.tooth_depth, self.tooth_depth_auto = self._auto_dspin(0.0, 30.0, 0.1)
        teeth_box = QGroupBox("Teeth (chevron / interdigitated)")
        tf = QFormLayout(teeth_box)
        tf.addRow("Teeth per boundary", self.num_fingers)
        tf.addRow("Tooth depth", self._with_auto(self.tooth_depth, self.tooth_depth_auto))
        root.addWidget(teeth_box)

        # Relief & rendering.
        self.corner_radius = self._dspin(0.0, 10.0, 0.1)
        self.arc_resolution = self._spin(2, 64, 1)
        self.relax = QCheckBox("Relax W + 2A = finger constraint")
        self.relax.toggled.connect(self._emit)
        misc_box = QGroupBox("Relief && rendering")
        mf = QFormLayout(misc_box)
        mf.addRow("Corner radius", self.corner_radius)
        mf.addRow("Arc resolution", self.arc_resolution)
        mf.addRow(self.relax)
        root.addWidget(misc_box)

        root.addStretch(1)

        self.name.textEdited.connect(self._emit)
        self.shape.currentIndexChanged.connect(self._on_shape)

    # -- signals ------------------------------------------------------------ #
    def _on_preset(self, index: int) -> None:
        if index <= 0:
            return
        key = self.preset.itemText(index)
        self.set_params(WHEEL_PRESETS[key])
        self.preset.setCurrentIndex(0)
        self.changed.emit()

    # -- params <-> form ---------------------------------------------------- #
    def params(self) -> WheelParams:
        """Read the form into a (possibly invalid, unvalidated) WheelParams."""
        return WheelParams(
            num_segments=self.num_segments.value(),
            segment_shape=self.shape.currentText(),
            segment_width=None if self.segment_width_auto.isChecked() else self.segment_width.value(),
            ring_width=self.ring_width.value(),
            air_gap=self.air_gap.value(),
            finger_diameter=self.finger_diameter.value(),
            num_fingers=self.num_fingers.value(),
            tooth_depth=None if self.tooth_depth_auto.isChecked() else self.tooth_depth.value(),
            corner_radius=self.corner_radius.value(),
            arc_resolution=self.arc_resolution.value(),
            relax_finger_constraint=self.relax.isChecked(),
            name=self.name.text() or "CT_Wheel",
        )

    def set_params(self, p: WheelParams) -> None:
        """Load *p* into the form without emitting :attr:`changed`."""
        self._loading = True
        try:
            self.name.setText(p.name)
            self.shape.setCurrentText(p.segment_shape)
            self.num_segments.setValue(p.num_segments)
            self.ring_width.setValue(p.ring_width)
            self.air_gap.setValue(p.air_gap)
            self.finger_diameter.setValue(p.finger_diameter)
            self.num_fingers.setValue(p.num_fingers)
            self.corner_radius.setValue(p.corner_radius)
            self.arc_resolution.setValue(p.arc_resolution)
            self.relax.setChecked(p.relax_finger_constraint)

            self.segment_width_auto.setChecked(p.segment_width is None)
            self.segment_width.setValue(p.width)
            self.tooth_depth_auto.setChecked(p.tooth_depth is None)
            self.tooth_depth.setValue(p.amplitude)

            self._on_shape()
        finally:
            self._loading = False
