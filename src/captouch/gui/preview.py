"""Live `QGraphicsView` preview of a :class:`SliderGeometry`.

The preview consumes the *same* geometry model the exporters serialise, so what
the user sees is byte-faithful to the emitted copper (the WYSIWYG guarantee from
``docs/plan.md`` section 3). Each electrode polygon is rendered from its exact
``Electrode.points``; the courtyard and fab outline mirror the footprint's
``F.CrtYd`` / ``F.Fab`` rectangles.

Coordinate space is geometry millimetres, identical to the footprint's. KiCad and
Qt's scene both use a y-down convention, so no axis flip is needed.

This module imports Qt but **no exporter and no file I/O** — it only draws.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView

from ..export.footprint import COURTYARD_MARGIN
from ..geometry import Electrode, SliderGeometry

__all__ = ["PreviewView", "LAYERS"]

#: Toggleable preview layers, in stacking order, with human labels.
LAYERS: tuple[tuple[str, str], ...] = (
    ("fab", "Fab outline"),
    ("courtyard", "Courtyard"),
    ("copper", "Active copper"),
    ("dummies", "Dummy (GND)"),
    ("anchors", "Pad anchors"),
    ("labels", "Pad numbers"),
)

# --- palette (loosely mirrors KiCad's pcbnew dark theme) ------------------- #
_BG = QColor("#1c2128")
_GRID = QColor("#2a313b")
_COPPER_FILL = QColor("#c5821f")
_COPPER_EDGE = QColor("#e6a23c")
_DUMMY_FILL = QColor("#4a565f")
_DUMMY_EDGE = QColor("#6c7a85")
_COURTYARD = QColor("#c46fb3")
_FAB = QColor("#9c7a4d")
_ANCHOR = QColor("#10141a")
_LABEL = QColor("#f0f0f0")

_ZOOM_STEP = 1.15
_FIT_MARGIN = 0.15  # fraction of the content size left as padding when fitting


def electrode_polygon(e: Electrode) -> QPolygonF:
    """The electrode's exterior ring as a closed :class:`QPolygonF`."""
    return QPolygonF([QPointF(x, y) for (x, y) in e.points])


class PreviewView(QGraphicsView):
    """Pan/zoom canvas drawing the current slider geometry."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)

        self.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing
        )
        self.setBackgroundBrush(QBrush(_BG))
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        # Qt scenes are y-down like KiCad; flip is unnecessary. Keep mm upright.

        self._geometry: SliderGeometry | None = None
        self._layer_items: dict[str, list] = {name: [] for name, _ in LAYERS}
        self._electrode_items: dict[str, object] = {}  # pad_number -> polygon item
        self._layer_visible: dict[str, bool] = {name: True for name, _ in LAYERS}
        self._layer_visible["anchors"] = False  # off by default (visual noise)

    # -- public API --------------------------------------------------------- #
    @property
    def geometry_model(self) -> SliderGeometry | None:
        """The geometry currently displayed (``None`` before the first render)."""
        return self._geometry

    def set_geometry(self, geo: SliderGeometry, *, fit: bool = False) -> None:
        """Render *geo*, preserving the current zoom/pan unless ``fit`` is set."""
        first = self._geometry is None
        self._geometry = geo
        self._rebuild_scene(geo)
        if fit or first:
            self.fit()

    def set_layer_visible(self, name: str, visible: bool) -> None:
        """Show/hide a named layer (see :data:`LAYERS`)."""
        if name not in self._layer_visible:
            raise KeyError(name)
        self._layer_visible[name] = visible
        for item in self._layer_items.get(name, []):
            item.setVisible(visible)

    def is_layer_visible(self, name: str) -> bool:
        return self._layer_visible[name]

    def electrode_polygon_points(self, pad_number: str) -> list[tuple[float, float]]:
        """Vertices actually drawn for an electrode — for WYSIWYG verification."""
        item = self._electrode_items[pad_number]
        poly = item.polygon()
        return [(round(p.x(), 4), round(p.y(), 4)) for p in poly]

    def fit(self) -> None:
        """Scale and centre so the whole widget fits with a small margin."""
        rect = self._content_rect()
        if rect.isEmpty():
            return
        pad_x = rect.width() * _FIT_MARGIN
        pad_y = rect.height() * _FIT_MARGIN
        self.fitInView(rect.adjusted(-pad_x, -pad_y, pad_x, pad_y), Qt.AspectRatioMode.KeepAspectRatio)

    def render_to_image(self, width: int = 1000, height: int = 360) -> QImage:
        """Render the current view to a :class:`QImage` (used for tests/screenshots)."""
        img = QImage(width, height, QImage.Format.Format_ARGB32)
        img.fill(_BG)
        painter = QPainter(img)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.render(painter)
        painter.end()
        return img

    # -- internals ---------------------------------------------------------- #
    def _content_rect(self) -> QRectF:
        """Bounding rect of the copper + courtyard in scene coordinates."""
        if self._geometry is None:
            return QRectF()
        minx, miny, maxx, maxy = self._geometry.bounds
        m = COURTYARD_MARGIN
        return QRectF(minx - m, miny - m, (maxx - minx) + 2 * m, (maxy - miny) + 2 * m)

    def _rebuild_scene(self, geo: SliderGeometry) -> None:
        self._scene.clear()
        self._layer_items = {name: [] for name, _ in LAYERS}
        self._electrode_items = {}

        minx, miny, maxx, maxy = geo.bounds
        m = COURTYARD_MARGIN

        # Fab documentation outline (drawn first / underneath).
        fab = self._scene.addRect(
            QRectF(minx, miny, maxx - minx, maxy - miny),
            self._cosmetic_pen(_FAB, 1.0),
            QBrush(Qt.BrushStyle.NoBrush),
        )
        self._register("fab", fab)

        # Courtyard.
        crt_pen = self._cosmetic_pen(_COURTYARD, 1.0, dashed=True)
        crt = self._scene.addRect(
            QRectF(minx - m, miny - m, (maxx - minx) + 2 * m, (maxy - miny) + 2 * m),
            crt_pen,
            QBrush(Qt.BrushStyle.NoBrush),
        )
        self._register("courtyard", crt)

        # Electrodes.
        for e in geo.electrodes:
            active = e.role == "active"
            fill = _COPPER_FILL if active else _DUMMY_FILL
            edge = _COPPER_EDGE if active else _DUMMY_EDGE
            poly_item = self._scene.addPolygon(
                electrode_polygon(e), self._cosmetic_pen(edge, 1.2), QBrush(fill)
            )
            self._register("copper" if active else "dummies", poly_item)
            self._electrode_items[e.pad_number] = poly_item

            # Pad anchor marker.
            ax, ay = e.anchor
            r = 0.3
            dot = self._scene.addEllipse(
                QRectF(ax - r, ay - r, 2 * r, 2 * r),
                self._cosmetic_pen(_ANCHOR, 1.0),
                QBrush(_ANCHOR),
            )
            self._register("anchors", dot)

            # Pad-number label centred on the anchor. The bounding rect is in the
            # item's (pixel) coordinates, so apply the mm scale to it too.
            label = self._scene.addSimpleText(e.pad_number)
            label.setBrush(QBrush(_LABEL))
            br = label.boundingRect()
            if br.height() > 0:
                scale = 2.0 / br.height()  # ~2 mm cap height
                label.setScale(scale)
                label.setPos(ax - br.width() * scale / 2.0, ay - br.height() * scale / 2.0)
            self._register("labels", label)

        self.setSceneRect(self._content_rect())

    def _register(self, layer: str, item) -> None:
        item.setVisible(self._layer_visible[layer])
        self._layer_items[layer].append(item)

    @staticmethod
    def _cosmetic_pen(color: QColor, width_px: float, *, dashed: bool = False) -> QPen:
        """A pen whose width is in device pixels (constant under zoom)."""
        pen = QPen(color)
        pen.setWidthF(width_px)
        pen.setCosmetic(True)
        if dashed:
            pen.setStyle(Qt.PenStyle.DashLine)
        return pen

    # -- interaction -------------------------------------------------------- #
    def wheelEvent(self, event) -> None:  # noqa: N802 (Qt override)
        delta = event.angleDelta().y()
        if delta == 0:
            return
        factor = _ZOOM_STEP if delta > 0 else 1.0 / _ZOOM_STEP
        self.scale(factor, factor)
