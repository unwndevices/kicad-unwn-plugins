"""Live `QGraphicsView` preview of a :class:`SliderGeometry`.

The preview consumes the *same* geometry model the exporters serialise, so what
the user sees is byte-faithful to the emitted copper (the WYSIWYG guarantee from
``docs/plan.md`` section 3). Each electrode polygon is rendered from its exact
``Electrode.points``; the courtyard and fab outline are drawn from the same
``fab_primitives`` / ``courtyard_outline`` the footprint exporter emits (rects
for a slider, circles for a wheel).

Coordinate space is geometry millimetres, identical to the footprint's. KiCad and
Qt's scene both use a y-down convention, so no axis flip is needed.

This module imports Qt but **no exporter and no file I/O** — it only draws.
"""

from __future__ import annotations

from typing import Union

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QGraphicsPolygonItem, QGraphicsScene, QGraphicsView

from ..export.footprint import COURTYARD_MARGIN
from ..geometry import (
    Electrode,
    KeypadGeometry,
    SliderGeometry,
    SupportCopper,
    TrackpadGeometry,
    WheelGeometry,
    build_support,
)
from ..geometry._base import polygon_points, rounded_rect_points
from ..geometry.zones import NETTIE_DIAMETER, NETTIE_DRILL

WidgetGeometry = Union[SliderGeometry, WheelGeometry, TrackpadGeometry, KeypadGeometry]

__all__ = ["PreviewView", "LAYERS"]

#: Toggleable preview layers, in stacking order, with human labels. ``back_copper``
#: and ``vias`` are only populated by the (two-layer) trackpad; ``ground`` and
#: ``guard`` only by the optional support copper.
LAYERS: tuple[tuple[str, str], ...] = (
    ("fab", "Fab outline"),
    ("courtyard", "Courtyard"),
    ("ground", "Ground pour"),
    ("back_copper", "B.Cu bridges"),
    ("copper", "F.Cu copper"),
    ("guard", "Guard ring"),
    ("dummies", "Dummy (GND)"),
    ("vias", "Vias"),
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
_BCU_FILL = QColor(64, 150, 160, 150)  # teal, semi-transparent (it's on the back)
_BCU_EDGE = QColor("#54b0bd")
# Optional support copper. Ground pour (B.Cu) hatched + translucent; guard ring
# (F.Cu) a translucent terracotta distinct from the electrode orange.
_GROUND_FILL = QColor(64, 150, 160, 70)
_GROUND_EDGE = QColor("#54b0bd")
_GUARD_FILL = QColor(210, 120, 90, 110)
_GUARD_EDGE = QColor("#d2785a")
_VIA_FILL = QColor("#c9d1d9")
_VIA_EDGE = QColor("#10141a")
_COURTYARD = QColor("#c46fb3")
_FAB = QColor("#9c7a4d")
_ANCHOR = QColor("#10141a")
_LABEL = QColor("#f0f0f0")

_ZOOM_STEP = 1.15
_FIT_MARGIN = 0.15  # fraction of the content size left as padding when fitting


def electrode_polygon(e: Electrode) -> QPolygonF:
    """The electrode's exterior ring as a closed :class:`QPolygonF`."""
    return QPolygonF([QPointF(x, y) for (x, y) in e.points])


def _qpoly(points) -> QPolygonF:
    """A list of ``(x, y)`` vertices as a :class:`QPolygonF`."""
    return QPolygonF([QPointF(x, y) for (x, y) in points])


def _ring(coords) -> QPolygonF:
    """A shapely ring's coordinates as a :class:`QPolygonF` (drop the closing dup)."""
    pts = list(coords)
    if pts and pts[0] == pts[-1]:
        pts = pts[:-1]
    return QPolygonF([QPointF(x, y) for (x, y) in pts])


def _qpath(poly) -> QPainterPath:
    """A shapely polygon (exterior + any holes) as a hole-faithful painter path."""
    path = QPainterPath()
    path.setFillRule(Qt.FillRule.OddEvenFill)
    path.addPolygon(_ring(poly.exterior.coords))
    for interior in poly.interiors:
        path.addPolygon(_ring(interior.coords))
    return path


class PreviewView(QGraphicsView):
    """Pan/zoom canvas drawing the current slider geometry."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)

        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        self.setBackgroundBrush(QBrush(_BG))
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        # Qt scenes are y-down like KiCad; flip is unnecessary. Keep mm upright.

        self._geometry: WidgetGeometry | None = None
        self._support: SupportCopper | None = None  # cached for the current geometry
        self._layer_items: dict[str, list] = {name: [] for name, _ in LAYERS}
        self._electrode_items: dict[str, QGraphicsPolygonItem] = {}  # pad_number -> item
        self._net_items: dict[str, list[QGraphicsPolygonItem]] = {}  # trackpad net items
        self._layer_visible: dict[str, bool] = {name: True for name, _ in LAYERS}
        self._layer_visible["anchors"] = False  # off by default (visual noise)

    # -- public API --------------------------------------------------------- #
    @property
    def geometry_model(self) -> WidgetGeometry | None:
        """The geometry currently displayed (``None`` before the first render)."""
        return self._geometry

    def set_geometry(self, geo: WidgetGeometry, *, fit: bool = False) -> None:
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
        return [(round(p.x(), 4), round(p.y(), 4)) for p in poly.toList()]

    def net_polygon_points(self, pad_number: str) -> list[list[tuple[float, float]]]:
        """Vertices drawn for every copper piece of a trackpad net (WYSIWYG check)."""
        out = []
        for item in self._net_items[pad_number]:
            out.append([(round(p.x(), 4), round(p.y(), 4)) for p in item.polygon().toList()])
        return out

    def fit(self) -> None:
        """Scale and centre so the whole widget fits with a small margin."""
        rect = self._content_rect()
        if rect.isEmpty():
            return
        pad_x = rect.width() * _FIT_MARGIN
        pad_y = rect.height() * _FIT_MARGIN
        self.fitInView(
            rect.adjusted(-pad_x, -pad_y, pad_x, pad_y), Qt.AspectRatioMode.KeepAspectRatio
        )

    def render_to_image(self, width: int = 1000, height: int = 360) -> QImage:
        """Render the current view to a :class:`QImage` (used for tests/screenshots)."""
        img = QImage(width, height, QImage.Format.Format_ARGB32)
        img.fill(_BG)
        painter = QPainter(img)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.render(painter)
        painter.end()
        return img

    def save_image(self, path: str, *, width: int = 1200) -> None:
        """Save the widget content to *path* as PNG (raster) or SVG (vector).

        The format is chosen by extension. Unlike :meth:`render_to_image`, this
        renders the *scene content* (the copper + courtyard, with margin), so the
        export captures the whole widget at its true aspect ratio regardless of
        the current zoom/pan.
        """
        src = self._content_rect()
        if src.isEmpty():
            raise RuntimeError("nothing to export — no geometry rendered yet")
        height = max(1, round(width * src.height() / src.width()))
        target = QRectF(0, 0, width, height)

        if path.lower().endswith(".svg"):
            from PySide6.QtSvg import QSvgGenerator

            gen = QSvgGenerator()
            gen.setFileName(path)
            gen.setSize(QSize(width, height))
            gen.setViewBox(target)
            painter = QPainter(gen)
            self._scene.render(painter, target, src)
            painter.end()
            return

        img = QImage(width, height, QImage.Format.Format_ARGB32)
        img.fill(_BG)
        painter = QPainter(img)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._scene.render(painter, target, src)
        painter.end()
        if not img.save(path):
            raise RuntimeError(f"could not write image to {path}")

    # -- internals ---------------------------------------------------------- #
    def _content_rect(self) -> QRectF:
        """Bounding rect of the copper + courtyard in scene coordinates."""
        if self._geometry is None:
            return QRectF()
        if self._support is not None:
            # The grown courtyard (already margin-padded) is the outermost extent.
            xs = [x for x, _ in self._support.courtyard_pts]
            ys = [y for _, y in self._support.courtyard_pts]
            return QRectF(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
        minx, miny, maxx, maxy = self._geometry.bounds
        m = COURTYARD_MARGIN
        return QRectF(minx - m, miny - m, (maxx - minx) + 2 * m, (maxy - miny) + 2 * m)

    def _rebuild_scene(self, geo) -> None:
        self._scene.clear()
        self._layer_items = {name: [] for name, _ in LAYERS}
        self._electrode_items = {}
        self._net_items = {}

        # Optional support copper. When present it replaces the widget's own fab /
        # courtyard with grown outlines that enclose the ground pour + guard ring,
        # exactly as the footprint exporter does.
        sc = build_support(geo)
        self._support = sc

        # Fab documentation outline (drawn first / underneath). Shapes come from
        # the geometry itself (rects for a slider, circles for a wheel), matching
        # exactly what the footprint exporter emits.
        fab_pen = self._cosmetic_pen(_FAB, 1.0)
        fab_prims = sc.fab_outlines if sc is not None else geo.fab_primitives
        for prim in fab_prims:
            self._register("fab", self._add_primitive(prim, fab_pen))

        # Courtyard: the bounding outline grown by the courtyard margin.
        crt_pen = self._cosmetic_pen(_COURTYARD, 1.0, dashed=True)
        if sc is not None:
            self._register(
                "courtyard",
                self._scene.addPolygon(
                    _qpoly(sc.courtyard_pts), crt_pen, QBrush(Qt.BrushStyle.NoBrush)
                ),
            )
        else:
            crt_prim = self._expand_primitive(geo.courtyard_outline, COURTYARD_MARGIN)
            self._register("courtyard", self._add_primitive(crt_prim, crt_pen))

        # Ground pour (B.Cu), drawn under the electrodes — a translucent hatch tint.
        if sc is not None and sc.ground is not None:
            self._register(
                "ground",
                self._scene.addPath(
                    _qpath(sc.ground),
                    self._cosmetic_pen(_GROUND_EDGE, 1.0),
                    QBrush(_GROUND_FILL, Qt.BrushStyle.BDiagPattern),
                ),
            )

        # The trackpad is two-layer (F.Cu diamonds + B.Cu via-bridges); slider and
        # wheel are single-layer electrodes. Branch on the geometry type so each
        # draws faithfully (the WYSIWYG guarantee) rather than via a lossy shim.
        if isinstance(geo, TrackpadGeometry):
            self._draw_trackpad(geo)
        else:
            self._draw_electrodes(geo)

        # Guard ring (F.Cu) + GND net-tie marker, drawn over the copper.
        if sc is not None:
            self._draw_support_overlay(sc)

        self.setSceneRect(self._content_rect())

    def _draw_electrodes(self, geo) -> None:
        """Render a slider / wheel: one filled polygon per electrode, + anchors."""
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

    def _draw_support_overlay(self, sc) -> None:
        """Draw the F.Cu guard ring and the thru-hole GND net-tie over the copper."""
        if sc.guard is not None:
            self._register(
                "guard",
                self._scene.addPath(
                    _qpath(sc.guard), self._cosmetic_pen(_GUARD_EDGE, 1.2), QBrush(_GUARD_FILL)
                ),
            )
        # The single thru-hole net-tie (outer copper + drilled hole), like a via.
        # Tied to whichever feature layer is on, so it hides with that toggle.
        layer = "guard" if sc.guard is not None else "ground"
        _, (tx, ty) = sc.net_tie
        d, drill = NETTIE_DIAMETER, NETTIE_DRILL
        ring = self._scene.addEllipse(
            QRectF(tx - d / 2, ty - d / 2, d, d),
            self._cosmetic_pen(_VIA_EDGE, 1.0),
            QBrush(_VIA_FILL),
        )
        hole = self._scene.addEllipse(
            QRectF(tx - drill / 2, ty - drill / 2, drill, drill),
            self._cosmetic_pen(_VIA_EDGE, 1.0),
            QBrush(_BG),
        )
        self._register(layer, ring)
        self._register(layer, hole)

    def _draw_trackpad(self, geo: TrackpadGeometry) -> None:
        """Render a trackpad: F.Cu diamonds/rows, B.Cu straps, and vias, by layer."""
        via_d = geo.params.via_diameter
        drill = geo.params.via_drill
        for net in geo.nets:
            items = self._net_items.setdefault(net.pad_number, [])
            # B.Cu straps first (drawn under the F.Cu copper).
            for poly in net.bcu:
                item = self._scene.addPolygon(
                    _qpoly(polygon_points(poly)),
                    self._cosmetic_pen(_BCU_EDGE, 1.0),
                    QBrush(_BCU_FILL),
                )
                self._register("back_copper", item)
                items.append(item)
            # F.Cu copper (diamonds + Rx necks).
            for poly in net.fcu:
                item = self._scene.addPolygon(
                    _qpoly(polygon_points(poly)),
                    self._cosmetic_pen(_COPPER_EDGE, 1.2),
                    QBrush(_COPPER_FILL),
                )
                self._register("copper", item)
                items.append(item)
            # Vias: outer annulus + drilled hole.
            for via in net.vias:
                ax, ay = via.at
                ring = self._scene.addEllipse(
                    QRectF(ax - via_d / 2, ay - via_d / 2, via_d, via_d),
                    self._cosmetic_pen(_VIA_EDGE, 1.0),
                    QBrush(_VIA_FILL),
                )
                hole = self._scene.addEllipse(
                    QRectF(ax - drill / 2, ay - drill / 2, drill, drill),
                    self._cosmetic_pen(_VIA_EDGE, 1.0),
                    QBrush(_BG),
                )
                self._register("vias", ring)
                self._register("vias", hole)
            # Anchor marker + pad-number label at the net's anchor.
            ax, ay = net.anchor
            r = 0.3
            dot = self._scene.addEllipse(
                QRectF(ax - r, ay - r, 2 * r, 2 * r),
                self._cosmetic_pen(_ANCHOR, 1.0),
                QBrush(_ANCHOR),
            )
            self._register("anchors", dot)
            label = self._scene.addSimpleText(net.pad_number)
            label.setBrush(QBrush(_LABEL))
            br = label.boundingRect()
            if br.height() > 0:
                scale = 2.0 / br.height()
                label.setScale(scale)
                label.setPos(ax - br.width() * scale / 2.0, ay - br.height() * scale / 2.0)
            self._register("labels", label)

    def _register(self, layer: str, item) -> None:
        item.setVisible(self._layer_visible[layer])
        self._layer_items[layer].append(item)

    def _add_primitive(self, prim: tuple, pen: QPen):
        """Draw a ``("rect"|"rrect"|"circle", …)`` outline primitive."""
        kind = prim[0]
        no_fill = QBrush(Qt.BrushStyle.NoBrush)
        if kind == "rect":
            _, x1, y1, x2, y2 = prim
            return self._scene.addRect(QRectF(x1, y1, x2 - x1, y2 - y1), pen, no_fill)
        if kind == "rrect":
            _, x1, y1, x2, y2, r = prim
            # Same vertex ring the exporter emits, so preview == output.
            return self._scene.addPolygon(
                _qpoly(rounded_rect_points(x1, y1, x2, y2, r)), pen, no_fill
            )
        if kind == "circle":
            _, cx, cy, r = prim
            return self._scene.addEllipse(QRectF(cx - r, cy - r, 2 * r, 2 * r), pen, no_fill)
        if kind == "poly":  # support-copper grown fab outline (a vertex ring)
            _, pts = prim
            return self._scene.addPolygon(_qpoly(pts), pen, no_fill)
        raise ValueError(f"unknown outline primitive: {prim!r}")

    @staticmethod
    def _expand_primitive(prim: tuple, margin: float) -> tuple:
        kind = prim[0]
        if kind == "rect":
            _, x1, y1, x2, y2 = prim
            return ("rect", x1 - margin, y1 - margin, x2 + margin, y2 + margin)
        if kind == "rrect":
            _, x1, y1, x2, y2, r = prim
            return ("rrect", x1 - margin, y1 - margin, x2 + margin, y2 + margin, r + margin)
        if kind == "circle":
            _, cx, cy, r = prim
            return ("circle", cx, cy, r + margin)
        raise ValueError(f"unknown outline primitive: {prim!r}")

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
