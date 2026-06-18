"""Shared form scaffolding for the per-widget parameter panels.

Both the slider and wheel panels are the same kind of thing — a grid of spin
boxes / combos bound to a frozen params dataclass that emits :attr:`changed` on
any edit. The widget-construction helpers and the edit-suppression guard live
here; each panel subclass only lays out its own fields and maps them to/from its
dataclass.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QSpinBox,
    QWidget,
)

__all__ = ["PanelBase", "PRESET_PLACEHOLDER"]

PRESET_PLACEHOLDER = "Load preset…"

# Red outline applied to a spin box the current validation error names.
_FIELD_ERR_STYLE = "border: 1px solid #e88;"


class PanelBase(QWidget):
    """Base parameter panel: a ``changed`` signal plus widget factories."""

    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._loading = False  # suppress `changed` while loading programmatically
        self._highlighted: list[QWidget] = []  # spin boxes currently flagged invalid

    # -- signals ------------------------------------------------------------ #
    def _emit(self, *args) -> None:
        if not self._loading:
            self.changed.emit()

    def _on_shape(self) -> None:
        """Enable the teeth controls only for chevron / interdigitated shapes.

        Relies on the subclass exposing ``shape``, ``num_fingers``,
        ``tooth_depth`` and ``tooth_depth_auto`` widgets.
        """
        teeth = self.shape.currentText() != "rectangular"
        self.num_fingers.setEnabled(teeth)
        self.tooth_depth_auto.setEnabled(teeth)
        self.tooth_depth.setEnabled(teeth and not self.tooth_depth_auto.isChecked())
        self._emit()

    # -- support copper (optional, default off) ----------------------------- #
    def _build_support_group(self) -> QGroupBox:
        """A "Support copper (optional)" group shared by every widget panel.

        Two opt-in, default-off features (matching :mod:`captouch.params.support`):
        a hatched ground pour on B.Cu and a guard / ESD ring on F.Cu. The spin-box
        attributes are named **exactly** after the params fields (``ground_margin``
        … ``guard_break``) so :meth:`show_error` highlights the right control on a
        validation failure. The ``ground_*`` spins are enable-gated on the
        ``ground_hatch`` checkbox and the ``guard_*`` spins on ``guard_ring``.
        """
        box = QGroupBox("Support copper (optional)")
        form = QFormLayout(box)

        # Hatched ground pour (B.Cu) — shields without solid-pour loading.
        self.ground_hatch = QCheckBox("Hatched ground pour (B.Cu)")
        self.ground_margin = self._dspin(0.0, 20.0, 0.5)
        self.ground_hatch_width = self._dspin(0.05, 2.0, 0.01)
        self.ground_hatch_pitch = self._dspin(0.1, 10.0, 0.1)
        form.addRow(self.ground_hatch)
        form.addRow("Ground margin (mm)", self.ground_margin)
        form.addRow("Hatch line width (mm)", self.ground_hatch_width)
        form.addRow("Hatch pitch (mm)", self.ground_hatch_pitch)

        # Guard / ESD ring (F.Cu) — broken loop, mask-free by default (§4.6).
        self.guard_ring = QCheckBox("Guard / ESD ring (F.Cu)")
        self.guard_width = self._dspin(0.1, 5.0, 0.1)
        self.guard_gap = self._dspin(0.1, 10.0, 0.5)
        self.guard_break = self._dspin(0.0, 5.0, 0.05)
        self.guard_mask_open = QCheckBox("Open solder mask over ring (§4.6)")
        form.addRow(self.guard_ring)
        form.addRow("Ring width (mm)", self.guard_width)
        form.addRow("Ring gap (mm)", self.guard_gap)
        form.addRow("Ring break (mm)", self.guard_break)
        form.addRow(self.guard_mask_open)

        # Re-gate on toggle (no emit there — emit is wired separately, as elsewhere).
        self.ground_hatch.toggled.connect(self._on_support_toggle)
        self.ground_hatch.toggled.connect(self._emit)
        self.guard_ring.toggled.connect(self._on_support_toggle)
        self.guard_ring.toggled.connect(self._emit)
        self.guard_mask_open.toggled.connect(self._emit)

        self._set_tooltips(
            {
                self.ground_hatch: (
                    "Add a meshed ground pour on the opposite layer (B.Cu) — shields "
                    "without the capacitive loading of a solid pour (guidelines §5.1)."
                ),
                self.ground_margin: "How far the ground pour extends past the electrodes (mm).",
                self.ground_hatch_width: "Hatch copper-line width (mm). Default 0.18 = 7 mil.",
                self.ground_hatch_pitch: (
                    "Hatch centre-to-centre pitch (mm); must exceed the line width. "
                    "Default 1.14 = 45 mil top layer (Infineon)."
                ),
                self.guard_ring: (
                    "Add a grounded guard / ESD ring on the electrode layer (F.Cu), "
                    "offset outward from the electrodes (§5.2)."
                ),
                self.guard_width: "Guard-ring band width (mm).",
                self.guard_gap: "Gap from the electrodes to the guard ring (mm) — §5.2.",
                self.guard_break: "Break in the ring (mm) so it is not a closed-loop antenna (§4.6).",
                self.guard_mask_open: "Expose the ESD ring through the solder mask (§4.6).",
            }
        )
        self._on_support_toggle()  # initial enable state
        return box

    def _on_support_toggle(self, *args) -> None:
        """Enable each feature's spin boxes only while its checkbox is ticked."""
        ground = self.ground_hatch.isChecked()
        for w in (self.ground_margin, self.ground_hatch_width, self.ground_hatch_pitch):
            w.setEnabled(ground)
        guard = self.guard_ring.isChecked()
        for w in (self.guard_width, self.guard_gap, self.guard_break, self.guard_mask_open):
            w.setEnabled(guard)

    def _support_kwargs(self) -> dict:
        """The support-copper field overrides to splice into a panel's ``params()``."""
        return dict(
            ground_hatch=self.ground_hatch.isChecked(),
            ground_margin=self.ground_margin.value(),
            ground_hatch_width=self.ground_hatch_width.value(),
            ground_hatch_pitch=self.ground_hatch_pitch.value(),
            guard_ring=self.guard_ring.isChecked(),
            guard_width=self.guard_width.value(),
            guard_gap=self.guard_gap.value(),
            guard_break=self.guard_break.value(),
            guard_mask_open=self.guard_mask_open.isChecked(),
        )

    def _load_support(self, p) -> None:
        """Load *p*'s support-copper fields into the form (call under ``_loading``)."""
        self.ground_hatch.setChecked(p.ground_hatch)
        self.ground_margin.setValue(p.ground_margin)
        self.ground_hatch_width.setValue(p.ground_hatch_width)
        self.ground_hatch_pitch.setValue(p.ground_hatch_pitch)
        self.guard_ring.setChecked(p.guard_ring)
        self.guard_width.setValue(p.guard_width)
        self.guard_gap.setValue(p.guard_gap)
        self.guard_break.setValue(p.guard_break)
        self.guard_mask_open.setChecked(p.guard_mask_open)
        self._on_support_toggle()

    # -- tooltips & inline validation --------------------------------------- #
    @staticmethod
    def _set_tooltips(tips: dict[QWidget, str]) -> None:
        """Attach a hover hint to each ``{widget: text}``."""
        for widget, text in tips.items():
            widget.setToolTip(text)

    def _numeric_widgets(self) -> dict[str, QWidget]:
        """Map each spin-box attribute to its name (== its params field name)."""
        return {
            name: w for name, w in vars(self).items() if isinstance(w, (QSpinBox, QDoubleSpinBox))
        }

    def show_error(self, message: str) -> None:
        """Outline every spin box whose params field name appears in *message*.

        Validation messages name the offending field (e.g. ``"air_gap must be
        > 0"``), so this points the user at the control to fix without parsing
        the geometry. Fields the message doesn't name are left untouched.
        """
        self.clear_error()
        for name, widget in self._numeric_widgets().items():
            if name in message:
                widget.setStyleSheet(_FIELD_ERR_STYLE)
                self._highlighted.append(widget)

    def clear_error(self) -> None:
        """Remove all inline validation outlines."""
        for widget in self._highlighted:
            widget.setStyleSheet("")
        self._highlighted.clear()

    # -- widget factories --------------------------------------------------- #
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
