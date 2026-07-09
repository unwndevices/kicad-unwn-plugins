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
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from ..geometry import build_wheel
from ..params import WHEEL_PRESETS, WHEEL_SEGMENT_SHAPES, WheelError, WheelParams
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
        self.shape.addItems(WHEEL_SEGMENT_SHAPES)
        self.num_segments = self._spin(3, 32, 1)
        # Design-from-size: enter an overall outer diameter; the count is derived.
        self.diameter_driven = QCheckBox("Design from outer diameter")
        self.target_diameter = self._dspin(5.0, 500.0, 1.0)
        self.target_diameter.setValue(40.0)
        self.derived_segments = QLabel("—")
        shape_box = QGroupBox("Shape && count")
        sf = QFormLayout(shape_box)
        sf.addRow("Name", self.name)
        sf.addRow("Boundary shape", self.shape)
        sf.addRow(self.diameter_driven)
        sf.addRow("Target outer Ø (mm)", self.target_diameter)
        sf.addRow("Derived segments", self.derived_segments)
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

        # Spiral swirl (spiral shape only).
        self.spiral_angle = self._dspin(0.0, 180.0, 5.0)
        spiral_box = QGroupBox("Spiral (swirl)")
        spf = QFormLayout(spiral_box)
        spf.addRow("Twist angle (deg)", self.spiral_angle)
        root.addWidget(spiral_box)

        # Relief & rendering.
        self.corner_radius = self._dspin(0.0, 10.0, 0.1)
        self.tip_radius = self._dspin(0.0, 5.0, 0.05)
        self.arc_resolution = self._spin(2, 64, 1)
        self.relax = QCheckBox("Relax W + 2A = finger constraint")
        self.relax.toggled.connect(self._emit)
        misc_box = QGroupBox("Relief && rendering")
        mf = QFormLayout(misc_box)
        mf.addRow("Corner radius", self.corner_radius)
        mf.addRow("Tip radius (chevron)", self.tip_radius)
        mf.addRow("Arc resolution", self.arc_resolution)
        mf.addRow(self.relax)
        root.addWidget(misc_box)

        # Optional support copper (hatched ground + guard ring), default off.
        root.addWidget(self._build_support_group())

        # Overlay / sensitivity inputs (advisory only; no geometry effect).
        root.addWidget(self._build_sensing_group())

        root.addStretch(1)

        self.name.textEdited.connect(self._emit)
        self.shape.currentIndexChanged.connect(self._on_shape)

        # The derived count depends on the target diameter, the ring width and the
        # pitch inputs (wired here, after every spin exists).
        self.diameter_driven.toggled.connect(self._on_diameter_mode)
        self.diameter_driven.toggled.connect(self._emit)
        for spin in (
            self.target_diameter,
            self.air_gap,
            self.finger_diameter,
            self.segment_width,
            self.ring_width,
        ):
            spin.valueChanged.connect(self._update_derived)
        self.segment_width_auto.toggled.connect(self._update_derived)
        self._on_diameter_mode()  # initial gating: count-driven by default

        self._set_tooltips(
            {
                self.name: "Base name for the generated .kicad_mod / .kicad_sym files.",
                self.diameter_driven: (
                    "Design from a target outer diameter: the segment count is derived "
                    "from the pitch (W + A) and ring width; the achieved diameter lands "
                    "within ~one pitch of the target."
                ),
                self.target_diameter: "Overall outer diameter (mm) to size the segment count to.",
                self.shape: "Electrode boundary style around the ring.",
                self.num_segments: "Electrode count around the ring (≥3). The wheel is continuous.",
                self.segment_width: (
                    "Arc width W (mm) at the mean radius. Auto derives W = finger − 2·gap."
                ),
                self.ring_width: "Radial extent of the ring (mm).",
                self.air_gap: "Copper-to-copper gap A (mm) between adjacent electrodes.",
                self.finger_diameter: "Finger contact-disc diameter (mm) used by the W + 2A check.",
                self.num_fingers: "Teeth per shared boundary (chevron / interdigitated).",
                self.tooth_depth: "Boundary half-amplitude (mm). Auto = 0.3·W; must stay below W/2.",
                self.spiral_angle: (
                    "Spiral shape only: boundary twist from the centre hole outward "
                    "(degrees). 0 = straight radial bars; larger = a tighter swirl."
                ),
                self.corner_radius: "Extra ESD convex-corner rounding (mm).",
                self.tip_radius: "Rounding (mm) for sharp chevron tooth-tips (ESD / etch relief).",
                self.arc_resolution: "Circle tessellation: polyline segments per 90° of arc.",
                self.relax: "Skip the W + 2A = finger-diameter check (deliberately odd geometry).",
            }
        )

    # -- signals ------------------------------------------------------------ #
    def _on_shape(self) -> None:
        """Gate the teeth controls and the spiral twist on the chosen shape.

        Like the base, the teeth controls (``num_fingers`` / ``tooth_depth``)
        are enabled only for the toothed shapes — here that means *not*
        rectangular and *not* spiral, since the spiral's twist replaces teeth.
        The spiral twist control is enabled only for the spiral shape. Emits
        ``changed`` as the base does.
        """
        shape = self.shape.currentText()
        teeth = shape not in ("rectangular", "spiral")
        self.num_fingers.setEnabled(teeth)
        self.tooth_depth_auto.setEnabled(teeth)
        self.tooth_depth.setEnabled(teeth and not self.tooth_depth_auto.isChecked())
        self.spiral_angle.setEnabled(shape == "spiral")
        self._emit()

    def _on_diameter_mode(self, *args) -> None:
        """Toggle between count-driven and diameter-driven segment entry."""
        size = self.diameter_driven.isChecked()
        self.target_diameter.setEnabled(size)
        self.derived_segments.setEnabled(size)
        self.num_segments.setEnabled(not size)  # derived → read-only in size mode
        self._update_derived()
        self._emit()

    def _update_derived(self, *args) -> None:
        """Show the segment count a diameter-driven wheel derives from its target."""
        if not self.diameter_driven.isChecked():
            self.derived_segments.setText("—")
            return
        try:
            p = self._raw_params().fit_to_diameter(self.target_diameter.value())
        except WheelError:
            self.derived_segments.setText("(invalid pitch)")
            return
        self.derived_segments.setText(
            f"{p.num_segments} segments  (achieved Ø {p.outer_diameter:.1f} mm)"
        )
        self.num_segments.blockSignals(True)  # mirror, don't re-trigger a rebuild
        self.num_segments.setValue(p.num_segments)
        self.num_segments.blockSignals(False)

    def _on_preset(self, index: int) -> None:
        if index <= 0:
            return
        key = self.preset.itemText(index)
        self.set_params(WHEEL_PRESETS[key])
        self.preset.setCurrentIndex(0)
        self.changed.emit()

    # -- params <-> form ---------------------------------------------------- #
    def _raw_params(self) -> WheelParams:
        """The form's params using the explicit segment count (no diameter sizing)."""
        return WheelParams(
            num_segments=self.num_segments.value(),
            segment_shape=self.shape.currentText(),
            segment_width=None
            if self.segment_width_auto.isChecked()
            else self.segment_width.value(),
            ring_width=self.ring_width.value(),
            air_gap=self.air_gap.value(),
            finger_diameter=self.finger_diameter.value(),
            num_fingers=self.num_fingers.value(),
            tooth_depth=None if self.tooth_depth_auto.isChecked() else self.tooth_depth.value(),
            spiral_angle=self.spiral_angle.value(),
            corner_radius=self.corner_radius.value(),
            tip_radius=self.tip_radius.value(),
            arc_resolution=self.arc_resolution.value(),
            relax_finger_constraint=self.relax.isChecked(),
            name=self.name.text() or "CT_Wheel",
            **self._support_kwargs(),
            **self._sensing_kwargs(),
        )

    def params(self) -> WheelParams:
        """Read the form into a (possibly invalid, unvalidated) WheelParams."""
        p = self._raw_params()
        if self.diameter_driven.isChecked():
            p = p.fit_to_diameter(self.target_diameter.value())
        return p

    def set_params(self, p: WheelParams) -> None:
        """Load *p* into the form without emitting :attr:`changed`."""
        self._loading = True
        try:
            # A loaded params set carries an explicit count, so show count-driven
            # mode (the wheel has no persistent diameter target to restore).
            self.diameter_driven.setChecked(False)
            self.name.setText(p.name)
            self.shape.setCurrentText(p.segment_shape)
            self.num_segments.setValue(p.num_segments)
            self.ring_width.setValue(p.ring_width)
            self.air_gap.setValue(p.air_gap)
            self.finger_diameter.setValue(p.finger_diameter)
            self.num_fingers.setValue(p.num_fingers)
            self.spiral_angle.setValue(p.spiral_angle)
            self.corner_radius.setValue(p.corner_radius)
            self.tip_radius.setValue(p.tip_radius)
            self.arc_resolution.setValue(p.arc_resolution)
            self.relax.setChecked(p.relax_finger_constraint)

            self.segment_width_auto.setChecked(p.segment_width is None)
            self.segment_width.setValue(p.width)
            self.tooth_depth_auto.setChecked(p.tooth_depth is None)
            self.tooth_depth.setValue(p.amplitude)

            self._load_support(p)
            self._load_sensing(p)
            self._on_shape()
            self._on_diameter_mode()  # count-driven gating after load
        finally:
            self._loading = False
