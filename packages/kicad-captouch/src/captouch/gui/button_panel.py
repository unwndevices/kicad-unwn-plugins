"""Parameter editor for a :class:`ButtonParams` (single self-cap button).

Outline, fill style, and the leg / hat dimensions, plus the shared support-copper
and overlay groups. Editing anything emits :attr:`changed`; the main window reads
:meth:`params` and rebuilds via :func:`~captouch.geometry.build_button`.
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

from ..geometry import build_button
from ..params import (
    BUTTON_HAT_STYLES,
    BUTTON_OUTLINES,
    BUTTON_PRESETS,
    BUTTON_STYLES,
    ButtonParams,
)
from ._panel_base import PRESET_PLACEHOLDER as _PRESET_PLACEHOLDER
from ._panel_base import PanelBase

__all__ = ["ButtonPanel"]


class ButtonPanel(PanelBase):
    """Form bound to a :class:`ButtonParams`; emits :attr:`changed` on any edit."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._build()
        self.set_params(ButtonParams())

    def build_geometry(self):
        """Build the button geometry for the current form (may raise ButtonError)."""
        return build_button(self.params())

    # -- construction ------------------------------------------------------- #
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        self.preset = QComboBox()
        self.preset.addItem(_PRESET_PLACEHOLDER)
        self.preset.addItems(sorted(BUTTON_PRESETS))
        self.preset.activated.connect(self._on_preset)
        preset_box = QGroupBox("Preset")
        pl = QVBoxLayout(preset_box)
        pl.addWidget(self.preset)
        root.addWidget(preset_box)

        self.name = QLineEdit()
        self.outline = QComboBox()
        self.outline.addItems(BUTTON_OUTLINES)
        self.outline_size = self._dspin(3.0, 80.0, 0.5)
        self.corner_radius = self._dspin(0.0, 20.0, 0.1)
        shape_box = QGroupBox("Outline (mm)")
        sf = QFormLayout(shape_box)
        sf.addRow("Name", self.name)
        sf.addRow("Outline", self.outline)
        sf.addRow("Size", self.outline_size)
        sf.addRow("Corner radius", self.corner_radius)
        root.addWidget(shape_box)

        self.fill_style = QComboBox()
        self.fill_style.addItems(BUTTON_STYLES)
        self.num_legs = self._spin(3, 32, 1)
        self.air_gap = self._dspin(0.15, 5.0, 0.05)
        self.leg_width, self.leg_width_auto = self._auto_dspin(0.15, 10.0, 0.05)
        self.hub_diameter, self.hub_diameter_auto = self._auto_dspin(0.5, 40.0, 0.5)
        self.rim_width, self.rim_width_auto = self._auto_dspin(0.0, 10.0, 0.05)
        self.ground_hat = QCheckBox("Ground hat (mesh GND between legs)")
        self.ground_hat.toggled.connect(self._emit)
        fill_box = QGroupBox("Fill / legs (mm)")
        ff = QFormLayout(fill_box)
        ff.addRow("Style", self.fill_style)
        ff.addRow("Legs / fingers", self.num_legs)
        ff.addRow("Spacing (air gap)", self.air_gap)
        ff.addRow("Leg width", self._with_auto(self.leg_width, self.leg_width_auto))
        ff.addRow("Hub diameter", self._with_auto(self.hub_diameter, self.hub_diameter_auto))
        ff.addRow("Rim width", self._with_auto(self.rim_width, self.rim_width_auto))
        ff.addRow(self.ground_hat)
        root.addWidget(fill_box)

        root.addWidget(self._build_support_group())
        root.addWidget(self._build_sensing_group())
        root.addStretch(1)

        self.name.textEdited.connect(self._emit)
        self.outline.currentIndexChanged.connect(self._on_style_changed)
        self.fill_style.currentIndexChanged.connect(self._on_style_changed)

        self._set_tooltips(
            {
                self.name: "Base name for the generated .kicad_mod / .kicad_sym files.",
                self.outline: "Outer shape: square (side = size) or circle (diameter = size).",
                self.outline_size: (
                    "Overall button size (mm). Should be ≥ 3 × the overlay thickness "
                    "(TI rule, guidelines §5.7)."
                ),
                self.corner_radius: "ESD corner rounding for a square outline (mm); ignored for circle.",
                self.fill_style: (
                    "Copper fill: solid pad, radial snowflake legs, parallel comb, "
                    "chevron (tapered) comb, or a low-Cp hatch mesh."
                ),
                self.num_legs: "Number of radial spokes or comb / chevron fingers.",
                self.air_gap: "Clearance between legs, or between a leg and the ground hat (mm).",
                self.leg_width: "Copper width of each leg / hatch line (mm). Auto fits the outline.",
                self.hub_diameter: "Centre pad diameter for the radial snowflake (mm).",
                self.rim_width: (
                    "Outer frame that keeps patterned copper connected (mm). "
                    "With a ground hat this is the hat's ring."
                ),
                self.ground_hat: (
                    "Pour the complementary copper as a GND pad so the legs mesh with a "
                    "grounded hat (radial / comb / chevron)."
                ),
            }
        )

    def _on_style_changed(self, *args) -> None:
        """Enable the controls that the current outline + style actually use."""
        style = self.fill_style.currentText()
        circle = self.outline.currentText() == "circle"
        patterned = style != "solid"
        legs = style in BUTTON_HAT_STYLES
        radial = style == "radial"
        hatch = style == "hatch"
        self.corner_radius.setEnabled(not circle)
        self.num_legs.setEnabled(legs)
        self.air_gap.setEnabled(patterned)
        self.leg_width_auto.setEnabled(patterned)
        self.leg_width.setEnabled(patterned and not self.leg_width_auto.isChecked())
        self.hub_diameter_auto.setEnabled(radial)
        self.hub_diameter.setEnabled(radial and not self.hub_diameter_auto.isChecked())
        self.rim_width_auto.setEnabled(patterned)
        self.rim_width.setEnabled(patterned and not self.rim_width_auto.isChecked())
        self.ground_hat.setEnabled(style in BUTTON_HAT_STYLES)
        if hatch or style == "solid":
            self.ground_hat.setChecked(False)
        self._emit()

    def _on_preset(self, index: int) -> None:
        if index <= 0:
            return
        key = self.preset.itemText(index)
        self.set_params(BUTTON_PRESETS[key])
        self.preset.setCurrentIndex(0)
        self.changed.emit()

    def params(self) -> ButtonParams:
        """Read the form into a (possibly invalid, unvalidated) ButtonParams."""
        return ButtonParams(
            outline=self.outline.currentText(),
            size=self.outline_size.value(),
            style=self.fill_style.currentText(),
            num_legs=self.num_legs.value(),
            air_gap=self.air_gap.value(),
            leg_width=None if self.leg_width_auto.isChecked() else self.leg_width.value(),
            hub_diameter=None if self.hub_diameter_auto.isChecked() else self.hub_diameter.value(),
            rim_width=None if self.rim_width_auto.isChecked() else self.rim_width.value(),
            ground_hat=self.ground_hat.isChecked(),
            corner_radius=self.corner_radius.value(),
            name=self.name.text() or "CT_Button",
            **self._support_kwargs(),
            **self._sensing_kwargs(),
        )

    def set_params(self, p: ButtonParams) -> None:
        """Load *p* into the form without emitting :attr:`changed`."""
        self._loading = True
        try:
            self.name.setText(p.name)
            self.outline.setCurrentText(p.outline)
            self.outline_size.setValue(p.size)
            self.fill_style.setCurrentText(p.style)
            self.num_legs.setValue(p.num_legs)
            self.air_gap.setValue(p.air_gap)
            self.leg_width_auto.setChecked(p.leg_width is None)
            self.leg_width.setValue(p.effective_leg_width)
            self.hub_diameter_auto.setChecked(p.hub_diameter is None)
            self.hub_diameter.setValue(p.effective_hub_diameter or 1.0)
            self.rim_width_auto.setChecked(p.rim_width is None)
            self.rim_width.setValue(p.effective_rim_width)
            self.ground_hat.setChecked(p.ground_hat)
            self.corner_radius.setValue(p.corner_radius)
            self._load_support(p)
            self._load_sensing(p)
            self._on_style_changed()
        finally:
            self._loading = False
