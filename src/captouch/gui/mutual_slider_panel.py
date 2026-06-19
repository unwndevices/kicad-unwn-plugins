"""Parameter editor for a :class:`MutualSliderParams` (mutual-cap diamond slider).

Combines the slider panel's "design from overall length" mode with the trackpad
panel's diamond / bridge / via knobs — fitting, since a mutual slider is a 1-D
diamond matrix. Editing anything emits :attr:`changed`; the main window reads
:meth:`params` and rebuilds via :func:`~captouch.geometry.build_mutual_slider`.
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

from ..geometry import build_mutual_slider
from ..params import (
    MAX_SENSE_ROWS,
    MIN_SEGMENTS,
    MUTUAL_SLIDER_PRESETS,
    MutualSliderError,
    MutualSliderParams,
)
from ._panel_base import PRESET_PLACEHOLDER as _PRESET_PLACEHOLDER
from ._panel_base import PanelBase

__all__ = ["MutualSliderPanel"]


class MutualSliderPanel(PanelBase):
    """Form bound to a :class:`MutualSliderParams`; emits :attr:`changed` on any edit."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._build()
        self.set_params(MutualSliderParams())

    def build_geometry(self):
        """Build the mutual-slider geometry for the current form (may raise)."""
        return build_mutual_slider(self.params())

    # -- construction ------------------------------------------------------- #
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        self.preset = QComboBox()
        self.preset.addItem(_PRESET_PLACEHOLDER)
        self.preset.addItems(sorted(MUTUAL_SLIDER_PRESETS))
        self.preset.activated.connect(self._on_preset)
        preset_box = QGroupBox("Preset")
        pl = QVBoxLayout(preset_box)
        pl.addWidget(self.preset)
        root.addWidget(preset_box)

        # Drive electrodes (Tx) = position nodes; sense rows (Rx) = 1 or 2.
        self.name = QLineEdit()
        self.num_segments = self._spin(MIN_SEGMENTS, 256, 1)
        self.sense_rows = self._spin(1, MAX_SENSE_ROWS, 1)
        # Design-from-size: enter an overall length and the node count is derived.
        self.length_driven = QCheckBox("Design from overall length")
        self.target_length = self._dspin(2.0, 1000.0, 1.0)
        self.target_length.setValue(60.0)
        self.derived_segments = QLabel("—")
        count_box = QGroupBox("Drive electrodes && sense rows")
        cf = QFormLayout(count_box)
        cf.addRow("Name", self.name)
        cf.addRow(self.length_driven)
        cf.addRow("Target length (mm)", self.target_length)
        cf.addRow("Derived nodes", self.derived_segments)
        cf.addRow("Drive electrodes (Tx)", self.num_segments)
        cf.addRow("Sense rows (Rx)", self.sense_rows)
        root.addWidget(count_box)

        # Diamonds.
        self.diamond_pitch = self._dspin(2.0, 12.0, 0.5)
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

        # Optional support copper (hatched ground + guard ring), default off.
        root.addWidget(self._build_support_group())

        # Overlay / sensitivity inputs (advisory only; no geometry effect).
        root.addWidget(self._build_sensing_group())

        root.addStretch(1)

        self.name.textEdited.connect(self._emit)
        # The derived node count depends on the target length and the pitch.
        self.length_driven.toggled.connect(self._on_length_mode)
        self.length_driven.toggled.connect(self._emit)
        self.target_length.valueChanged.connect(self._update_derived)
        self.diamond_pitch.valueChanged.connect(self._update_derived)
        self._on_length_mode()  # initial gating: count-driven by default

        self._set_tooltips(
            {
                self.name: "Base name for the generated .kicad_mod / .kicad_sym files.",
                self.length_driven: (
                    "Design from a target overall length: the node count is derived from "
                    "the diamond pitch; the achieved length lands within ~half a pitch."
                ),
                self.target_length: "Overall slider length (mm) to size the node count to.",
                self.num_segments: (
                    "Tx drive electrodes = position nodes (≥3). Each is bridged on B.Cu "
                    "over the continuous Rx sense line."
                ),
                self.sense_rows: (
                    "Rx sense rows: 1 = a single continuous sense line (Microchip §2.4), "
                    "2 = a dual-row layout for a stronger mutual signal (Infineon DSD)."
                ),
                self.diamond_pitch: "Drive-electrode centre spacing P (mm) — position granularity.",
                self.diamond_gap: "Copper-to-copper gap A (mm) between diamonds.",
                self.bridge_width: "F.Cu neck / B.Cu strap width (mm) at a Tx bridge.",
                self.via_drill: "Bridge via finished hole diameter (mm).",
                self.via_diameter: "Bridge via outer copper diameter (mm). Annular ring ≥ 0.1 mm.",
            }
        )

    # -- signals ------------------------------------------------------------ #
    def _on_length_mode(self, *args) -> None:
        """Toggle between count-driven and length-driven node entry."""
        size = self.length_driven.isChecked()
        self.target_length.setEnabled(size)
        self.derived_segments.setEnabled(size)
        self.num_segments.setEnabled(not size)  # derived → read-only in size mode
        self._update_derived()
        self._emit()

    def _update_derived(self, *args) -> None:
        """Show the node count a length-driven slider derives from its target."""
        if not self.length_driven.isChecked():
            self.derived_segments.setText("—")
            return
        try:
            p = self._raw_params().fit_to_length(self.target_length.value())
        except MutualSliderError:
            self.derived_segments.setText("(invalid pitch)")
            return
        self.derived_segments.setText(f"{p.num_segments} nodes  (achieved {p.total_length:.1f} mm)")
        self.num_segments.blockSignals(True)  # mirror, don't re-trigger a rebuild
        self.num_segments.setValue(p.num_segments)
        self.num_segments.blockSignals(False)

    def _on_preset(self, index: int) -> None:
        if index <= 0:
            return
        key = self.preset.itemText(index)
        self.set_params(MUTUAL_SLIDER_PRESETS[key])
        self.preset.setCurrentIndex(0)  # reset to placeholder; menu is action-only
        self.changed.emit()

    # -- params <-> form ---------------------------------------------------- #
    def _raw_params(self) -> MutualSliderParams:
        """The form's params using the explicit node count (no length sizing)."""
        return MutualSliderParams(
            num_segments=self.num_segments.value(),
            sense_rows=self.sense_rows.value(),
            diamond_pitch=self.diamond_pitch.value(),
            diamond_gap=self.diamond_gap.value(),
            bridge_width=self.bridge_width.value(),
            via_drill=self.via_drill.value(),
            via_diameter=self.via_diameter.value(),
            name=self.name.text() or "CT_MutualSlider",
            **self._support_kwargs(),
            **self._sensing_kwargs(),
        )

    def params(self) -> MutualSliderParams:
        """Read the form into a (possibly invalid, unvalidated) MutualSliderParams."""
        p = self._raw_params()
        if self.length_driven.isChecked():
            p = p.fit_to_length(self.target_length.value())
        return p

    def set_params(self, p: MutualSliderParams) -> None:
        """Load *p* into the form without emitting :attr:`changed`."""
        self._loading = True
        try:
            # A loaded params set carries an explicit count, so show count-driven
            # mode (there is no persistent length target to restore).
            self.length_driven.setChecked(False)
            self.name.setText(p.name)
            self.num_segments.setValue(p.num_segments)
            self.sense_rows.setValue(p.sense_rows)
            self.diamond_pitch.setValue(p.diamond_pitch)
            self.diamond_gap.setValue(p.diamond_gap)
            self.bridge_width.setValue(p.bridge_width)
            self.via_drill.setValue(p.via_drill)
            self.via_diameter.setValue(p.via_diameter)
            self._load_support(p)
            self._load_sensing(p)
            self._on_length_mode()  # count-driven gating after load
        finally:
            self._loading = False
