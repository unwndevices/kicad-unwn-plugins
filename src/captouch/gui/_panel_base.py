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
