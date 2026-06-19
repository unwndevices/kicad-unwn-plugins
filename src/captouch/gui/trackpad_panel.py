"""Parameter editor for a :class:`TrackpadParams` (XY diamond trackpad).

Mirrors the slider / wheel panels but for the trackpad's fields: a mutual-cap
diamond matrix has no shape / teeth / finger knobs — just the matrix size, the
diamond pitch and gap, and the bridge / via dimensions. Editing anything emits
:attr:`changed`.
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

from ..geometry import build_trackpad
from ..params import CLIP_MODES, MASK_SHAPES, TRACKPAD_PRESETS, TrackpadParams
from ._panel_base import PRESET_PLACEHOLDER as _PRESET_PLACEHOLDER
from ._panel_base import PanelBase

__all__ = ["TrackpadPanel"]


class TrackpadPanel(PanelBase):
    """Form bound to a :class:`TrackpadParams`; emits :attr:`changed` on any edit."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._build()
        self.set_params(TrackpadParams())

    def build_geometry(self):
        """Build the trackpad geometry for the current form (may raise TrackpadError)."""
        return build_trackpad(self.params())

    # -- construction ------------------------------------------------------- #
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        self.preset = QComboBox()
        self.preset.addItem(_PRESET_PLACEHOLDER)
        self.preset.addItems(sorted(TRACKPAD_PRESETS))
        self.preset.activated.connect(self._on_preset)
        preset_box = QGroupBox("Preset")
        pl = QVBoxLayout(preset_box)
        pl.addWidget(self.preset)
        root.addWidget(preset_box)

        # Matrix.
        self.name = QLineEdit()
        # No upper cap on the matrix (large pads are allowed); 2 is the structural
        # floor for a 2-D XY matrix. 999 is just the spin box's practical ceiling.
        self.num_rows = self._spin(2, 999, 1)
        self.num_cols = self._spin(2, 999, 1)
        # Design-from-size: enter an overall outline and the row/column counts are
        # derived from the pitch (the lattice is trimmed / inset to the exact size).
        self.size_driven = QCheckBox("Design from overall size")
        self.panel_width = self._dspin(2.0, 1000.0, 1.0)
        self.panel_height = self._dspin(2.0, 1000.0, 1.0)
        self.panel_width.setValue(50.0)
        self.panel_height.setValue(40.0)
        self.derived_counts = QLabel("—")
        matrix_box = QGroupBox("Matrix")
        mf = QFormLayout(matrix_box)
        mf.addRow("Name", self.name)
        mf.addRow(self.size_driven)
        mf.addRow("Target width (mm)", self.panel_width)
        mf.addRow("Target height (mm)", self.panel_height)
        mf.addRow("Derived matrix", self.derived_counts)
        mf.addRow("Rx rows (sense)", self.num_rows)
        mf.addRow("Tx columns (drive)", self.num_cols)
        root.addWidget(matrix_box)

        # Re-derive the count label whenever a size-driving input changes, and gate
        # which inputs are live on the mode toggle.
        self.size_driven.toggled.connect(self._on_size_mode)
        self.size_driven.toggled.connect(self._emit)
        self.panel_width.valueChanged.connect(self._update_derived)
        self.panel_height.valueChanged.connect(self._update_derived)

        # Diamonds.
        self.diamond_pitch = self._dspin(2.0, 12.0, 0.5)
        self.diamond_pitch.valueChanged.connect(self._update_derived)  # pitch → counts
        self.diamond_gap = self._dspin(0.1, 2.0, 0.05)
        dim_box = QGroupBox("Diamonds (mm)")
        df = QFormLayout(dim_box)
        df.addRow("Pitch", self.diamond_pitch)
        df.addRow("Gap", self.diamond_gap)
        root.addWidget(dim_box)

        # Bridges & vias.
        self.bridge_width = self._dspin(0.1, 2.0, 0.05)
        self.via_drill = self._dspin(0.1, 1.0, 0.05)
        self.via_diameter = self._dspin(0.2, 2.0, 0.05)
        bridge_box = QGroupBox("Bridges && vias (mm)")
        bf = QFormLayout(bridge_box)
        bf.addRow("Bridge / neck width", self.bridge_width)
        bf.addRow("Via drill", self.via_drill)
        bf.addRow("Via diameter", self.via_diameter)
        root.addWidget(bridge_box)

        # Outer mask: rect (default), rounded-rect, or circle. corner_radius
        # applies to rrect, radius to circle (Auto = inscribed 0.5·min(W,H)).
        self.mask_shape = QComboBox()
        self.mask_shape.addItems(MASK_SHAPES)
        self.mask_shape.currentTextChanged.connect(self._on_mask)
        self.clip_mode = QComboBox()
        self.clip_mode.addItems(CLIP_MODES)
        self.clip_mode.currentTextChanged.connect(self._emit)
        self.corner_radius = self._dspin(0.5, 20.0, 0.5)
        self.corner_radius.setValue(2.0)
        self.radius, self.radius_auto = self._auto_dspin(1.0, 50.0, 0.5)
        self.radius_auto.setChecked(True)
        mask_box = QGroupBox("Mask")
        mf2 = QFormLayout(mask_box)
        mf2.addRow("Shape", self.mask_shape)
        mf2.addRow("Clip mode", self.clip_mode)
        mf2.addRow("Corner radius (mm)", self.corner_radius)
        mf2.addRow("Radius (mm)", self._with_auto(self.radius, self.radius_auto))
        root.addWidget(mask_box)

        # Optional support copper (hatched ground + guard ring), default off.
        root.addWidget(self._build_support_group())

        # Overlay / sensitivity inputs (advisory only; no geometry effect).
        root.addWidget(self._build_sensing_group())

        root.addStretch(1)

        self.name.textEdited.connect(self._emit)
        self._on_mask()  # set initial enabled state for the default rect mask
        self._on_size_mode()  # initial gating: count-driven by default

        self._set_tooltips(
            {
                self.name: "Base name for the generated .kicad_mod / .kicad_sym files.",
                self.size_driven: (
                    "Design from a target overall size: the row/column counts are "
                    "derived from the pitch and the lattice is trimmed / inset to the "
                    "exact outline (e.g. a 300×200 mm enclosure cutout)."
                ),
                self.panel_width: "Overall outline width (mm); columns = round(width / pitch).",
                self.panel_height: "Overall outline height (mm); rows = round(height / pitch).",
                self.num_rows: "Rx (sense) rows on F.Cu (≥ 2; no upper cap).",
                self.num_cols: "Tx (drive) columns bridged on B.Cu (≥ 2; no upper cap).",
                self.diamond_pitch: "Row/column centre spacing P (mm).",
                self.diamond_gap: "Copper-to-copper gap A (mm) between diamonds.",
                self.bridge_width: "F.Cu neck / B.Cu strap width (mm) at a Tx bridge.",
                self.via_drill: "Bridge via finished hole diameter (mm).",
                self.via_diameter: "Bridge via outer copper diameter (mm). Annular ring ≥ 0.1 mm.",
                self.mask_shape: "Outer outline: rect (default), rounded-rect, or circle.",
                self.clip_mode: (
                    "Curved-mask diamonds: inscribe (kept whole or dropped) or "
                    "conform (cut to the curve, Azoteq Fig 6.3). Inert for a rect mask."
                ),
                self.corner_radius: "Rounded-rect fillet radius (mm); used with the rrect mask.",
                self.radius: "Circle mask radius (mm). Auto = inscribed 0.5·min(width, height).",
            }
        )

    # -- signals ------------------------------------------------------------ #
    def _on_mask(self, *args) -> None:
        """Enable corner_radius for rrect and the radius row for circle only."""
        shape = self.mask_shape.currentText()
        # clip_mode (inscribe/conform) only changes a curved mask; a rect clips
        # nothing, so the choice is inert there.
        self.clip_mode.setEnabled(shape != "rect")
        self.corner_radius.setEnabled(shape == "rrect")
        self.radius_auto.setEnabled(shape == "circle")
        self.radius.setEnabled(shape == "circle" and not self.radius_auto.isChecked())
        self._emit()

    def _on_size_mode(self, *args) -> None:
        """Toggle between count-driven (rows/cols) and size-driven (panel) entry."""
        size = self.size_driven.isChecked()
        self.panel_width.setEnabled(size)
        self.panel_height.setEnabled(size)
        self.derived_counts.setEnabled(size)
        # In size mode the counts are derived, so the manual spins are read-only.
        self.num_rows.setEnabled(not size)
        self.num_cols.setEnabled(not size)
        self._update_derived()
        self._emit()

    def _update_derived(self, *args) -> None:
        """Show the row/column counts a size-driven pad derives from its target."""
        if not self.size_driven.isChecked():
            self.derived_counts.setText("—")
            return
        sized = TrackpadParams.from_size(
            self.panel_width.value(),
            self.panel_height.value(),
            diamond_pitch=self.diamond_pitch.value(),
        )
        self.derived_counts.setText(
            f"{sized.num_cols} cols × {sized.num_rows} rows  "
            f"(lattice {sized.lattice_width:.0f}×{sized.lattice_height:.0f} mm)"
        )
        # Mirror the derived counts into the (read-only) manual spins so they agree
        # with the label; block signals so this display sync doesn't trigger a rebuild.
        for spin, value in ((self.num_cols, sized.num_cols), (self.num_rows, sized.num_rows)):
            spin.blockSignals(True)
            spin.setValue(value)
            spin.blockSignals(False)

    def _on_preset(self, index: int) -> None:
        if index <= 0:
            return
        key = self.preset.itemText(index)
        self.set_params(TRACKPAD_PRESETS[key])
        self.preset.setCurrentIndex(0)
        self.changed.emit()

    # -- params <-> form ---------------------------------------------------- #
    def params(self) -> TrackpadParams:
        """Read the form into a (possibly invalid, unvalidated) TrackpadParams."""
        shape = self.mask_shape.currentText()
        kw: dict = dict(
            diamond_pitch=self.diamond_pitch.value(),
            diamond_gap=self.diamond_gap.value(),
            bridge_width=self.bridge_width.value(),
            via_drill=self.via_drill.value(),
            via_diameter=self.via_diameter.value(),
            mask_shape=shape,
            clip_mode=self.clip_mode.currentText(),
            name=self.name.text() or "CT_Trackpad",
        )
        # Size-driven: derive the counts from the target outline and pin the panel;
        # otherwise take the explicit row/column counts.
        if self.size_driven.isChecked():
            sized = TrackpadParams.from_size(
                self.panel_width.value(),
                self.panel_height.value(),
                diamond_pitch=self.diamond_pitch.value(),
            )
            kw["num_rows"] = sized.num_rows
            kw["num_cols"] = sized.num_cols
            kw["panel_width"] = sized.panel_width
            kw["panel_height"] = sized.panel_height
        else:
            kw["num_rows"] = self.num_rows.value()
            kw["num_cols"] = self.num_cols.value()
        # corner_radius / radius are only valid for their own shape (validation
        # rejects a stray value otherwise), so include each only when it applies.
        if shape == "rrect":
            kw["corner_radius"] = self.corner_radius.value()
        if shape == "circle" and not self.radius_auto.isChecked():
            kw["radius"] = self.radius.value()
        kw.update(self._support_kwargs())
        kw.update(self._sensing_kwargs())
        return TrackpadParams(**kw)

    def set_params(self, p: TrackpadParams) -> None:
        """Load *p* into the form without emitting :attr:`changed`."""
        self._loading = True
        try:
            self.name.setText(p.name)
            # A params set with a panel was designed from an overall size: restore
            # that mode and the target, plus the (derived) counts for when it's off.
            self.size_driven.setChecked(p.panel_width is not None and p.panel_height is not None)
            if p.panel_width is not None and p.panel_height is not None:
                self.panel_width.setValue(p.panel_width)
                self.panel_height.setValue(p.panel_height)
            self.num_rows.setValue(p.num_rows)
            self.num_cols.setValue(p.num_cols)
            self.diamond_pitch.setValue(p.diamond_pitch)
            self.diamond_gap.setValue(p.diamond_gap)
            self.bridge_width.setValue(p.bridge_width)
            self.via_drill.setValue(p.via_drill)
            self.via_diameter.setValue(p.via_diameter)
            self.mask_shape.setCurrentText(p.mask_shape)
            self.clip_mode.setCurrentText(p.clip_mode)
            if p.corner_radius:
                self.corner_radius.setValue(p.corner_radius)
            self.radius_auto.setChecked(p.radius is None)
            if p.radius is not None:
                self.radius.setValue(p.radius)
            self._load_support(p)
            self._load_sensing(p)
            self._on_mask()
            self._on_size_mode()
        finally:
            self._loading = False
