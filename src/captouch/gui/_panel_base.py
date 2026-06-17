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
    QHBoxLayout,
    QSpinBox,
    QWidget,
)

__all__ = ["PanelBase", "PRESET_PLACEHOLDER"]

PRESET_PLACEHOLDER = "Load preset…"


class PanelBase(QWidget):
    """Base parameter panel: a ``changed`` signal plus widget factories."""

    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._loading = False  # suppress `changed` while loading programmatically

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
