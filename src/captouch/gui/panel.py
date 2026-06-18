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

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QLineEdit,
    QVBoxLayout,
)

from ..geometry import build_slider
from ..params import SLIDER_PRESETS, SliderParams
from ..params.slider import SEGMENT_SHAPES
from ._panel_base import PRESET_PLACEHOLDER as _PRESET_PLACEHOLDER
from ._panel_base import PanelBase

__all__ = ["ParamPanel"]


class ParamPanel(PanelBase):
    """Form bound to a :class:`SliderParams`; emits :attr:`changed` on any edit."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._build()
        self.set_params(SliderParams())

    def build_geometry(self):
        """Build the slider geometry for the current form (may raise SliderError)."""
        return build_slider(self.params())

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
        self.tip_radius = self._dspin(0.0, 5.0, 0.05)
        self.relax = QCheckBox("Relax W + 2A = finger constraint")
        self.relax.toggled.connect(self._emit)
        end_box = QGroupBox("Ends && relief")
        ef = QFormLayout(end_box)
        ef.addRow("End dummies / side", self.end_dummies)
        ef.addRow("Corner radius", self.corner_radius)
        ef.addRow("Tip radius (chevron)", self.tip_radius)
        ef.addRow(self.relax)
        root.addWidget(end_box)

        # Optional support copper (hatched ground + guard ring), default off.
        root.addWidget(self._build_support_group())

        root.addStretch(1)

        self.name.textEdited.connect(self._emit)
        self.shape.currentIndexChanged.connect(self._on_shape)

        self._set_tooltips(
            {
                self.name: "Base name for the generated .kicad_mod / .kicad_sym files.",
                self.shape: (
                    "Electrode edge style. Chevron / interdigitated stretch the crossover "
                    "so a finger always overlaps ≥2 segments (linear interpolation)."
                ),
                self.num_segments: "Active (sensed) electrode count. ≥3 for usable interpolation.",
                self.segment_width: (
                    "Segment width W (mm). Auto derives W = finger − 2·gap so that "
                    "W + 2A = finger diameter (Infineon AN85951 Eq. 73)."
                ),
                self.segment_height: "Electrode height H (mm) — the slider's transverse dimension.",
                self.air_gap: "Copper-to-copper gap A (mm) between adjacent electrodes.",
                self.finger_diameter: "Finger contact-disc diameter (mm) used by the W + 2A check.",
                self.num_fingers: "Teeth per shared boundary (chevron / interdigitated).",
                self.tooth_depth: "Boundary half-amplitude (mm). Auto = 0.3·W; must stay below W/2.",
                self.end_dummies: "Grounded dummy segments per end (0–2) for uniform end feel.",
                self.corner_radius: "Extra ESD convex-corner rounding (mm), applied to all shapes.",
                self.tip_radius: "Rounding (mm) for sharp chevron tooth-tips (ESD / etch relief).",
                self.relax: "Skip the W + 2A = finger-diameter check (deliberately odd geometry).",
            }
        )

    # -- signals ------------------------------------------------------------ #
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
            segment_width=None
            if self.segment_width_auto.isChecked()
            else self.segment_width.value(),
            segment_height=self.segment_height.value(),
            air_gap=self.air_gap.value(),
            finger_diameter=self.finger_diameter.value(),
            num_fingers=self.num_fingers.value(),
            tooth_depth=None if self.tooth_depth_auto.isChecked() else self.tooth_depth.value(),
            end_dummies=self.end_dummies.value(),
            corner_radius=self.corner_radius.value(),
            tip_radius=self.tip_radius.value(),
            relax_finger_constraint=self.relax.isChecked(),
            name=self.name.text() or "CT_Slider",
            **self._support_kwargs(),
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
            self.tip_radius.setValue(p.tip_radius)
            self.relax.setChecked(p.relax_finger_constraint)

            # Optional fields: Auto reflects None; spin shows the resolved value.
            self.segment_width_auto.setChecked(p.segment_width is None)
            self.segment_width.setValue(p.width)
            self.tooth_depth_auto.setChecked(p.tooth_depth is None)
            self.tooth_depth.setValue(p.amplitude)

            self._load_support(p)
            self._on_shape()  # sync enable-state to the loaded shape
        finally:
            self._loading = False
