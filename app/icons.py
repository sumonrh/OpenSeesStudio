"""Vector toolbar icons drawn with QPainter (no external assets)."""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QIcon, QPainter, QPainterPath, QPen,
                           QPixmap, QPolygonF)

_CACHE: dict = {}

INK = "#1f3a5f"
ACCENT = "#0f6fb8"
ORANGE = "#e8622c"
GREEN = "#2f9e5f"


def _pen(p: QPainter, color=INK, w=1.6):
    p.setPen(QPen(QColor(color), w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(Qt.NoBrush)


def _fill(p: QPainter, color):
    p.setBrush(QBrush(QColor(color)))
    p.setPen(Qt.NoPen)


def icon(name: str, size: int = 26, accent: str = ACCENT) -> QIcon:
    key = (name, size, accent)
    if key in _CACHE:
        return _CACHE[key]
    pm = QPixmap(size * 2, size * 2)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.scale(size * 2 / 24.0, size * 2 / 24.0)
    try:
        _draw(p, name, accent)
    finally:
        p.end()
    ic = QIcon(pm)
    _CACHE[key] = ic
    return ic


def _dot(p, x, y, r=1.9, color=INK):
    _fill(p, color)
    p.drawEllipse(QPointF(x, y), r, r)


def _arrow_head(p, x, y, dx, dy, s=2.4):
    import math
    ang = math.atan2(dy, dx)
    a1 = ang + 2.6
    a2 = ang - 2.6
    pts = [QPointF(x, y),
           QPointF(x + s * math.cos(a1), y + s * math.sin(a1)),
           QPointF(x + s * math.cos(a2), y + s * math.sin(a2))]
    _fill(p, p.pen().color().name() if p.pen().color().alpha() else INK)
    p.drawPolygon(QPolygonF(pts))


def _draw(p: QPainter, name: str, accent: str) -> None:
    if name == "new":
        _pen(p)
        path = QPainterPath()
        path.moveTo(5, 2.5); path.lineTo(14, 2.5); path.lineTo(19, 7.5)
        path.lineTo(19, 21.5); path.lineTo(5, 21.5); path.closeSubpath()
        p.drawPath(path)
        p.drawPolyline([QPointF(14, 2.5), QPointF(14, 7.5), QPointF(19, 7.5)])
        pen = QPen(QColor(accent), 1.6)
        p.setPen(pen)
        p.drawLine(QPointF(12, 11), QPointF(12, 17.5))
        p.drawLine(QPointF(8.75, 14.25), QPointF(15.25, 14.25))

    elif name == "open":
        _pen(p)
        path = QPainterPath()
        path.moveTo(2.5, 6.5); path.lineTo(9.5, 6.5); path.lineTo(11.5, 9)
        path.lineTo(21, 9); path.lineTo(21, 19.5); path.lineTo(2.5, 19.5)
        path.closeSubpath()
        p.drawPath(path)
        pen = QPen(QColor(accent), 1.6)
        p.setPen(pen)
        p.drawLine(QPointF(2.5, 12), QPointF(21, 12))

    elif name == "save":
        _pen(p)
        p.drawRoundedRect(QRectF(3, 3, 18, 18), 1.4, 1.4)
        p.drawRect(QRectF(7.5, 3, 9, 6))
        p.drawRect(QRectF(6.5, 13, 11, 8))
        _fill(p, accent)
        p.drawRect(QRectF(14.5, 4.5, 2.2, 3.2))

    elif name == "node":
        _pen(p, "#93a7bd", 1.2)
        p.drawLine(QPointF(12, 2.5), QPointF(12, 21.5))
        p.drawLine(QPointF(2.5, 12), QPointF(21.5, 12))
        _fill(p, accent)
        p.drawEllipse(QPointF(12, 12), 4.2, 4.2)
        p.setPen(QPen(QColor("#ffffff"), 1.0))
        p.drawEllipse(QPointF(12, 12), 2.1, 2.1)

    elif name == "element":
        _pen(p, accent, 1.8)
        p.drawLine(QPointF(5, 18.5), QPointF(19, 5.5))
        _fill(p, INK)
        p.drawEllipse(QPointF(5, 18.5), 2.3, 2.3)
        p.drawEllipse(QPointF(19, 5.5), 2.3, 2.3)

    elif name == "copy":
        _pen(p, "#8ea6bd")
        p.drawRoundedRect(QRectF(3, 3, 11, 11), 1.2, 1.2)
        _pen(p, accent)
        p.drawRoundedRect(QRectF(9.5, 9.5, 11, 11), 1.2, 1.2)

    elif name == "move":
        _pen(p, accent, 1.7)
        p.drawLine(QPointF(12, 3.5), QPointF(12, 20.5))
        p.drawLine(QPointF(3.5, 12), QPointF(20.5, 12))
        p.setPen(QPen(QColor(accent), 1.7, Qt.SolidLine, Qt.RoundCap))
        for (x, y, dx, dy) in ((12, 3.5, 0, -1), (12, 20.5, 0, 1),
                               (3.5, 12, -1, 0), (20.5, 12, 1, 0)):
            _fill(p, accent)
            _arrow_head(p, x, y, dx, dy, 2.6)

    elif name == "mirror":
        _pen(p, "#8ea6bd", 1.4)
        p.drawLine(QPointF(12, 2.5), QPointF(12, 21.5))
        _pen(p, accent, 1.6)
        tri1 = QPolygonF([QPointF(2.5, 6), QPointF(2.5, 18), QPointF(9.5, 12)])
        p.drawPolygon(tri1)
        _pen(p, GREEN, 1.6)
        tri2 = QPolygonF([QPointF(21.5, 6), QPointF(21.5, 18), QPointF(14.5, 12)])
        p.drawPolygon(tri2)

    elif name == "rotate":
        _pen(p, accent, 1.7)
        path = QPainterPath()
        path.arcMoveTo(QRectF(4, 4, 16, 16), 40)
        path.arcTo(QRectF(4, 4, 16, 16), 40, 280)
        p.drawPath(path)
        _fill(p, accent)
        _arrow_head(p, 18.5, 6.2, 1, -1.4, 2.8)

    elif name == "support":
        _pen(p, GREEN, 1.7)
        tri = QPolygonF([QPointF(12, 5), QPointF(5, 17), QPointF(19, 17)])
        p.drawPolygon(tri)
        p.drawLine(QPointF(3.5, 17), QPointF(20.5, 17))
        for i in range(5):
            x = 4.2 + i * 3.9
            p.drawLine(QPointF(x, 17), QPointF(x - 2.2, 20.5))

    elif name == "load":
        _pen(p, accent, 1.8)
        p.drawLine(QPointF(12, 3), QPointF(12, 18))
        _fill(p, accent)
        _arrow_head(p, 12, 20.5, 0, 1, 3.4)
        p.setPen(QPen(QColor("#8ea6bd"), 1.4))
        p.drawLine(QPointF(4.5, 21.5), QPointF(19.5, 21.5))

    elif name == "case":
        _pen(p, "#8ea6bd", 1.2)
        p.drawRect(QRectF(5, 3.5, 14, 4))
        _pen(p, accent, 1.4)
        p.drawRect(QRectF(4, 9, 16, 4.5))
        p.drawRect(QRectF(4, 15, 16, 4.5))

    elif name == "combo":
        _pen(p, "#8ea6bd", 1.3)
        for i, y in enumerate((4, 8.5, 13)):
            p.drawRect(QRectF(3, y, 12, 3.2))
        _fill(p, accent)
        p.drawEllipse(QPointF(19, 9), 4.4, 4.4)
        p.setPen(QPen(QColor("#ffffff"), 1.4))
        p.drawLine(QPointF(19, 6.6), QPointF(19, 11.4))
        p.drawLine(QPointF(16.8, 9), QPointF(21.2, 9))

    elif name == "run":
        _fill(p, GREEN)
        p.drawPolygon(QPolygonF([QPointF(7, 4), QPointF(20, 12), QPointF(7, 20)]))

    elif name == "results":
        _pen(p)
        p.drawLine(QPointF(3, 20.5), QPointF(21, 20.5))
        p.drawLine(QPointF(3.5, 3), QPointF(3.5, 20.5))
        _fill(p, accent)
        p.drawRect(QRectF(6, 13, 3, 6))
        p.drawRect(QRectF(11, 9, 3, 10))
        p.drawRect(QRectF(16, 5, 3, 14))

    elif name == "tables":
        _pen(p, accent)
        p.drawRect(QRectF(3, 4, 18, 16))
        p.setPen(QPen(QColor(accent), 1.2))
        p.drawLine(QPointF(3, 9), QPointF(21, 9))
        p.drawLine(QPointF(3, 14.5), QPointF(21, 14.5))
        p.drawLine(QPointF(9, 4), QPointF(9, 20))
        p.drawLine(QPointF(15, 4), QPointF(15, 20))

    elif name == "fit":
        _pen(p, accent, 1.7)
        for x, y, sx, sy in ((3, 3, 1, 1), (21, 3, -1, 1), (3, 21, 1, -1), (21, 21, -1, -1)):
            p.drawLine(QPointF(x, y + sy * 6), QPointF(x, y))
            p.drawLine(QPointF(x, y), QPointF(x + sx * 6, y))

    elif name in ("iso", "top", "front", "right"):
        _pen(p, "#a9b9ca", 1.2)
        cx, cy = 12, 13
        top = QPolygonF([QPointF(cx, cy - 8), QPointF(cx + 8, cy - 4),
                         QPointF(cx, cy), QPointF(cx - 8, cy - 4)])
        left = QPolygonF([QPointF(cx - 8, cy - 4), QPointF(cx, cy),
                          QPointF(cx, cy + 8), QPointF(cx - 8, cy + 4)])
        right = QPolygonF([QPointF(cx + 8, cy - 4), QPointF(cx, cy),
                           QPointF(cx, cy + 8), QPointF(cx + 8, cy + 4)])
        if name == "iso":
            _fill(p, accent); p.drawPolygon(top)
            _fill(p, "#8fb4d6"); p.drawPolygon(left)
            _fill(p, "#c5d9ec"); p.drawPolygon(right)
        else:
            p.drawPolygon(top); p.drawPolygon(left); p.drawPolygon(right)
            face = {"top": top, "front": left, "right": right}[name]
            _fill(p, QColor(accent).lighter(120))
            p.drawPolygon(face)

    elif name == "delete":
        _pen(p, ORANGE, 1.9)
        p.drawLine(QPointF(5.5, 5.5), QPointF(18.5, 18.5))
        p.drawLine(QPointF(18.5, 5.5), QPointF(5.5, 18.5))

    elif name == "undo":
        _pen(p, accent, 1.7)
        path = QPainterPath()
        path.arcMoveTo(QRectF(4, 6, 16, 13), 160)
        path.arcTo(QRectF(4, 6, 16, 13), 160, -250)
        p.drawPath(path)
        _fill(p, accent)
        _arrow_head(p, 5.2, 9.6, -1, 1.2, 2.8)

    elif name == "redo":
        _pen(p, accent, 1.7)
        path = QPainterPath()
        path.arcMoveTo(QRectF(4, 6, 16, 13), 20)
        path.arcTo(QRectF(4, 6, 16, 13), 20, 250)
        p.drawPath(path)
        _fill(p, accent)
        _arrow_head(p, 18.8, 9.6, 1, 1.2, 2.8)

    elif name == "settings":
        _pen(p, "#5a7391", 1.5)
        p.drawEllipse(QPointF(12, 12), 3.2, 3.2)
        p.drawEllipse(QPointF(12, 12), 8.2, 8.2)
        p.setPen(QPen(QColor("#5a7391"), 3.4))
        for a in range(0, 360, 45):
            import math
            r1, r2 = 7.6, 10.4
            x1 = 12 + r1 * math.cos(math.radians(a))
            y1 = 12 + r1 * math.sin(math.radians(a))
            x2 = 12 + r2 * math.cos(math.radians(a))
            y2 = 12 + r2 * math.sin(math.radians(a))
            p.drawLine(QPointF(x1, y1), QPointF(x2, y2))

    elif name == "select":
        _pen(p, INK, 1.5)
        path = QPainterPath()
        path.moveTo(6, 3); path.lineTo(6, 19); path.lineTo(10.5, 15)
        path.lineTo(13.5, 21); path.lineTo(16.5, 19.5); path.lineTo(13.5, 13.8)
        path.lineTo(19, 13.5); path.closeSubpath()
        _fill(p, "#ffffff"); p.drawPath(path)

    elif name in ("lock", "unlock"):
        _pen(p, INK, 1.6)
        p.drawRoundedRect(QRectF(6, 10.5, 12, 9.5), 1.5, 1.5)
        if name == "lock":
            p.drawArc(QRectF(8, 4.5, 8, 10), 0, 180 * 16)
            p.drawLine(QPointF(8, 9.5), QPointF(8, 10.5))
            p.drawLine(QPointF(16, 9.5), QPointF(16, 10.5))
        else:
            p.drawArc(QRectF(9, 3.5, 8, 10), 20 * 16, 160 * 16)
            p.drawLine(QPointF(16.6, 9.3), QPointF(16.6, 10.5))
        _fill(p, accent)
        p.drawEllipse(QPointF(12, 14.6), 1.5, 1.5)
        p.drawRect(QRectF(11.4, 15.2, 1.2, 2.6))

    elif name == "panel":
        _pen(p, INK, 1.5)
        p.drawRoundedRect(QRectF(3, 4, 18, 16), 2, 2)
        p.drawLine(QPointF(14.5, 4), QPointF(14.5, 20))

    elif name == "menu":
        _fill(p, INK)
        for row in range(3):
            for col in range(3):
                p.drawEllipse(QPointF(6 + col * 6, 6 + row * 6), 1.7, 1.7)

    elif name == "about":
        _pen(p, accent, 1.6)
        p.drawEllipse(QPointF(12, 12), 8.6, 8.6)
        _fill(p, accent)
        p.drawEllipse(QPointF(12, 7.4), 1.3, 1.3)
        p.setPen(QPen(QColor(accent), 2.0, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(12, 11), QPointF(12, 17))

    else:  # generic square
        _pen(p, "#8ea6bd")
        p.drawRect(QRectF(5, 5, 14, 14))


def app_icon(size: int = 256) -> QIcon:
    """Application icon: a portal frame on a blue gradient tile."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    rect = QRectF(2, 2, size - 4, size - 4)
    grad = __import__("PySide6.QtGui", fromlist=["QLinearGradient"]).QLinearGradient(
        0, 0, size, size)
    grad.setColorAt(0.0, QColor("#1c4f7c"))
    grad.setColorAt(1.0, QColor("#0f7ab8"))
    p.setBrush(QBrush(grad))
    p.setPen(QPen(QColor("#0b3f68"), max(1.0, size * 0.012)))
    p.drawRoundedRect(rect, size * 0.20, size * 0.20)

    p.setPen(QPen(QColor("#ffffff"), size * 0.045, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    left = size * 0.26
    right = size * 0.74
    base = size * 0.76
    top = size * 0.36
    p.drawLine(QPointF(left, base), QPointF(left, top))
    p.drawLine(QPointF(right, base), QPointF(right, top))
    p.drawLine(QPointF(left, top), QPointF(right, top))
    p.drawLine(QPointF(left, size * 0.56), QPointF(right, size * 0.56))
    p.setPen(QPen(QColor("#8fd0f5"), size * 0.035, Qt.DashLine))
    p.drawLine(QPointF(left, base), QPointF(right, top))
    p.setBrush(QBrush(QColor("#ffb27a")))
    p.setPen(Qt.NoPen)
    for x, y in ((left, top), (right, top), (left, size * 0.56),
                 (right, size * 0.56), (left, base), (right, base)):
        p.drawEllipse(QPointF(x, y), size * 0.032, size * 0.032)
    p.end()
    return QIcon(pm)
