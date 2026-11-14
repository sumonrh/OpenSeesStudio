"""Vector toolbar icons drawn with QPainter (no external assets)."""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QIcon, QPainter, QPainterPath,
                           QPen, QPixmap, QPolygonF)

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

    elif name == "batch_element":
        _pen(p, "#8ea6bd", 1.4)
        for offset in (-3.5, 0.0, 3.5):
            p.drawLine(QPointF(4.0, 18.0 + offset),
                       QPointF(20.0, 6.0 + offset))
        _fill(p, accent)
        for offset in (-3.5, 0.0, 3.5):
            p.drawEllipse(QPointF(4.0, 18.0 + offset), 1.8, 1.8)
            p.drawEllipse(QPointF(20.0, 6.0 + offset), 1.8, 1.8)

    elif name == "draw_element":
        _pen(p, accent, 1.8)
        p.drawLine(QPointF(4.5, 19.5), QPointF(19.5, 4.5))
        _fill(p, INK)
        p.drawEllipse(QPointF(4.5, 19.5), 2.4, 2.4)
        p.drawEllipse(QPointF(19.5, 4.5), 2.4, 2.4)
        _pen(p, ORANGE, 1.4)
        p.drawLine(QPointF(14.0, 19.0), QPointF(20.5, 12.5))
        p.drawLine(QPointF(14.0, 19.0), QPointF(15.6, 18.3))
        p.drawLine(QPointF(14.0, 19.0), QPointF(14.7, 17.4))

    elif name == "activate":
        _pen(p, accent, 1.5)
        p.drawArc(QRectF(3.0, 7.0, 18.0, 10.0), 0, 180 * 16)
        p.drawArc(QRectF(3.0, 7.0, 18.0, 10.0), 180 * 16, 180 * 16)
        _fill(p, accent)
        p.drawEllipse(QPointF(12.0, 12.0), 3.0, 3.0)
        _pen(p, GREEN, 1.8)
        p.drawLine(QPointF(15.0, 18.5), QPointF(17.0, 20.5))
        p.drawLine(QPointF(17.0, 20.5), QPointF(21.0, 15.0))

    elif name == "deactivate":
        _pen(p, accent, 1.5)
        p.drawArc(QRectF(3.0, 7.0, 18.0, 10.0), 0, 180 * 16)
        p.drawArc(QRectF(3.0, 7.0, 18.0, 10.0), 180 * 16, 180 * 16)
        _fill(p, accent)
        p.drawEllipse(QPointF(12.0, 12.0), 3.0, 3.0)
        _pen(p, ORANGE, 2.0)
        p.drawLine(QPointF(4.0, 21.0), QPointF(20.0, 3.0))

    elif name == "activate_all":
        _pen(p, accent, 1.5)
        p.drawArc(QRectF(3.0, 6.0, 18.0, 9.0), 0, 180 * 16)
        p.drawArc(QRectF(3.0, 6.0, 18.0, 9.0), 180 * 16, 180 * 16)
        _fill(p, accent)
        p.drawEllipse(QPointF(12.0, 10.5), 2.7, 2.7)
        _pen(p, GREEN, 1.6)
        p.drawLine(QPointF(4.5, 20.0), QPointF(9.5, 20.0))
        p.drawLine(QPointF(7.5, 17.5), QPointF(4.5, 20.0))
        p.drawLine(QPointF(7.5, 22.5), QPointF(4.5, 20.0))
        p.drawLine(QPointF(14.5, 20.0), QPointF(19.5, 20.0))
        p.drawLine(QPointF(16.5, 17.5), QPointF(19.5, 20.0))
        p.drawLine(QPointF(16.5, 22.5), QPointF(19.5, 20.0))

    elif name == "subdivide":
        _pen(p, "#8ea6bd", 1.8)
        p.drawLine(QPointF(4, 20), QPointF(20, 4))
        _pen(p, accent, 1.5)
        for i in range(1, 4):
            f = i / 4.0
            x, y = 4 + 16 * f, 20 - 16 * f
            p.drawLine(QPointF(x - 1.5, y - 2.4), QPointF(x + 1.5, y + 2.4))
        _fill(p, INK)
        p.drawEllipse(QPointF(4, 20), 2.0, 2.0)
        p.drawEllipse(QPointF(20, 4), 2.0, 2.0)

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

    elif name == "run_static":
        _fill(p, GREEN)
        p.drawPolygon(QPolygonF([QPointF(4, 4), QPointF(13, 12), QPointF(4, 20)]))
        _pen(p, accent, 1.5)
        for y, ln in ((7, 5), (12, 8), (17, 6)):
            p.drawLine(QPointF(15, y), QPointF(15 + ln, y))

    elif name == "modal":
        _pen(p, accent, 1.8)
        path = QPainterPath()
        path.moveTo(3, 12)
        path.cubicTo(6, 2, 9, 2, 12, 12)
        path.cubicTo(15, 22, 18, 22, 21, 12)
        p.drawPath(path)
        _fill(p, GREEN)
        p.drawPolygon(QPolygonF([QPointF(2.5, 8), QPointF(6, 10.5), QPointF(2.5, 13)]))

    elif name == "animate":
        _pen(p, accent, 1.3)
        p.drawArc(QRectF(3, 4, 9, 16), 90 * 16, 180 * 16)
        p.drawArc(QRectF(12, 4, 9, 16), 270 * 16, 180 * 16)
        _fill(p, GREEN)
        p.drawPolygon(QPolygonF([QPointF(8, 6), QPointF(18, 12), QPointF(8, 18)]))

    elif name == "check":
        _pen(p, GREEN, 1.7)
        path = QPainterPath()
        path.moveTo(12, 2.5); path.lineTo(20, 6); path.lineTo(20, 12)
        path.lineTo(12, 21.5); path.lineTo(4, 12); path.lineTo(4, 6)
        path.closeSubpath()
        p.drawPath(path)
        _pen(p, GREEN, 2.2)
        p.drawPolyline([QPointF(7.5, 12), QPointF(10.8, 15.2), QPointF(16.8, 8.5)])

    elif name == "material":
        for i, color in enumerate(("#c5d9ec", "#8fb4d6", accent)):
            y = 5 + i * 5
            poly = QPolygonF([QPointF(12, y), QPointF(21, y + 3.5),
                              QPointF(12, y + 7), QPointF(3, y + 3.5)])
            _fill(p, color)
            p.drawPolygon(poly)

    elif name == "section":
        _pen(p, accent, 1.4)
        pts = [(6, 3), (18, 3), (18, 7), (14, 7), (14, 17), (18, 17),
               (18, 21), (6, 21), (6, 17), (10, 17), (10, 7), (6, 7)]
        _fill(p, "#dcebf9")
        p.drawPolygon(QPolygonF([QPointF(x, y) for x, y in pts]))

    elif name == "nodal_load":
        _pen(p, accent, 1.7)
        p.drawLine(QPointF(8, 3), QPointF(8, 14))
        _fill(p, accent)
        _arrow_head(p, 8, 16.5, 0, 1, 3.2)
        _fill(p, ORANGE)
        p.drawEllipse(QPointF(8, 20), 2.6, 2.6)
        _pen(p, "#8ea6bd", 1.2)
        p.drawLine(QPointF(4, 22), QPointF(20, 22))

    elif name == "element_load":
        _pen(p, "#8ea6bd", 1.4)
        p.drawLine(QPointF(3, 19), QPointF(21, 19))
        _pen(p, accent, 1.5)
        for x in (7, 12, 17):
            p.drawLine(QPointF(x, 4), QPointF(x, 14))
            _fill(p, accent)
            _arrow_head(p, x, 16.4, 0, 1, 2.9)

    elif name == "self_weight":
        _pen(p, INK, 1.4)
        p.drawRect(QRectF(5, 6, 14, 9))
        _fill(p, "#dcebf9")
        p.drawRect(QRectF(6, 7, 12, 7))
        _pen(p, accent, 1.6)
        p.drawLine(QPointF(12, 16), QPointF(12, 21))
        _fill(p, accent)
        _arrow_head(p, 12, 22.5, 0, 1, 2.8)
        p.setFont(QFont("Segoe UI", 6, QFont.Bold))
        p.setPen(QPen(QColor(INK)))
        p.drawText(QPointF(9.3, 13.2), "g")

    elif name == "label":
        _pen(p, INK, 1.3)
        path = QPainterPath()
        path.moveTo(3, 6); path.lineTo(14, 6); path.lineTo(21, 12)
        path.lineTo(14, 18); path.lineTo(3, 18); path.closeSubpath()
        _fill(p, "#ffffff")
        p.drawPath(path)
        p.setFont(QFont("Segoe UI", 7, QFont.Bold))
        p.drawText(QPointF(7.6, 15.5), "A")

    elif name == "node_label":
        _pen(p, INK, 1.3)
        path = QPainterPath()
        path.moveTo(3, 6); path.lineTo(14, 6); path.lineTo(21, 12)
        path.lineTo(14, 18); path.lineTo(3, 18); path.closeSubpath()
        _fill(p, "#ffffff")
        p.drawPath(path)
        p.setFont(QFont("Segoe UI", 7, QFont.Bold))
        p.drawText(QPointF(7.4, 15.5), "N")

    elif name == "element_label":
        _pen(p, INK, 1.3)
        path = QPainterPath()
        path.moveTo(3, 6); path.lineTo(14, 6); path.lineTo(21, 12)
        path.lineTo(14, 18); path.lineTo(3, 18); path.closeSubpath()
        _fill(p, "#ffffff")
        p.drawPath(path)
        p.setFont(QFont("Segoe UI", 7, QFont.Bold))
        p.drawText(QPointF(7.4, 15.5), "E")

    elif name == "frame2d":
        _pen(p, accent, 1.7)
        p.drawLine(QPointF(4.5, 20.5), QPointF(4.5, 6.5))
        p.drawLine(QPointF(19.5, 20.5), QPointF(19.5, 6.5))
        p.drawLine(QPointF(4.5, 6.5), QPointF(19.5, 6.5))
        _pen(p, "#8ea6bd", 1.5)
        p.drawLine(QPointF(4.5, 13.5), QPointF(19.5, 13.5))

    elif name == "frame3d":
        _pen(p, accent, 1.5)
        p.drawLine(QPointF(3.5, 20.0), QPointF(3.5, 9.0))
        p.drawLine(QPointF(13.5, 20.0), QPointF(13.5, 9.0))
        p.drawLine(QPointF(3.5, 9.0), QPointF(13.5, 9.0))
        _pen(p, "#8ea6bd", 1.3)
        p.drawLine(QPointF(9.5, 16.0), QPointF(9.5, 5.0))
        p.drawLine(QPointF(19.5, 16.0), QPointF(19.5, 5.0))
        p.drawLine(QPointF(9.5, 5.0), QPointF(19.5, 5.0))
        p.drawLine(QPointF(3.5, 9.0), QPointF(9.5, 5.0))
        p.drawLine(QPointF(13.5, 9.0), QPointF(19.5, 5.0))
        p.drawLine(QPointF(3.5, 20.0), QPointF(9.5, 16.0))
        p.drawLine(QPointF(13.5, 20.0), QPointF(19.5, 16.0))

    elif name == "truss2d":
        _pen(p, accent, 1.5)
        p.drawLine(QPointF(3, 19.5), QPointF(21, 19.5))
        p.drawLine(QPointF(3, 7.5), QPointF(21, 7.5))
        for x in (3, 9, 15, 21):
            p.drawLine(QPointF(x, 7.5), QPointF(x, 19.5))
        p.drawLine(QPointF(3, 19.5), QPointF(9, 7.5))
        p.drawLine(QPointF(9, 7.5), QPointF(15, 19.5))
        p.drawLine(QPointF(15, 19.5), QPointF(21, 7.5))

    elif name == "truss3d":
        _pen(p, accent, 1.4)
        p.drawLine(QPointF(2.5, 19.0), QPointF(15.5, 19.0))
        p.drawLine(QPointF(2.5, 9.0), QPointF(15.5, 9.0))
        p.drawLine(QPointF(2.5, 19.0), QPointF(2.5, 9.0))
        p.drawLine(QPointF(15.5, 19.0), QPointF(15.5, 9.0))
        p.drawLine(QPointF(2.5, 19.0), QPointF(9.0, 9.0))
        p.drawLine(QPointF(9.0, 9.0), QPointF(15.5, 19.0))
        _pen(p, "#8ea6bd", 1.2)
        p.drawLine(QPointF(8.5, 15.0), QPointF(21.5, 15.0))
        p.drawLine(QPointF(8.5, 5.0), QPointF(21.5, 5.0))
        p.drawLine(QPointF(8.5, 15.0), QPointF(8.5, 5.0))
        p.drawLine(QPointF(21.5, 15.0), QPointF(21.5, 5.0))
        p.drawLine(QPointF(2.5, 9.0), QPointF(8.5, 5.0))
        p.drawLine(QPointF(15.5, 9.0), QPointF(21.5, 5.0))
        p.drawLine(QPointF(2.5, 19.0), QPointF(8.5, 15.0))
        p.drawLine(QPointF(15.5, 19.0), QPointF(21.5, 15.0))

    elif name == "bridge":
        _pen(p, "#8ea6bd", 1.7)
        p.drawLine(QPointF(7.0, 12.0), QPointF(7.0, 21.0))
        p.drawLine(QPointF(17.0, 12.0), QPointF(17.0, 21.0))
        p.drawLine(QPointF(3.5, 21.0), QPointF(20.5, 21.0))
        _pen(p, accent, 2.2)
        p.drawLine(QPointF(2.0, 11.0), QPointF(22.0, 11.0))
        _pen(p, accent, 1.3)
        p.drawLine(QPointF(2.0, 13.5), QPointF(22.0, 13.5))
        for x in (7.0, 17.0):
            p.drawLine(QPointF(x - 1.6, 13.5), QPointF(x + 1.6, 11.0))
            p.drawLine(QPointF(x + 1.6, 13.5), QPointF(x - 1.6, 11.0))

    elif name == "import_tcl":
        _pen(p, accent, 1.8)
        p.drawLine(QPointF(12, 3.5), QPointF(12, 14))
        p.drawLine(QPointF(8.5, 10.5), QPointF(12, 14))
        p.drawLine(QPointF(15.5, 10.5), QPointF(12, 14))
        _pen(p, INK, 1.5)
        p.drawLine(QPointF(4, 16.5), QPointF(4, 20.5))
        p.drawLine(QPointF(4, 20.5), QPointF(20, 20.5))
        p.drawLine(QPointF(20, 20.5), QPointF(20, 16.5))

    elif name == "console":
        _pen(p, INK, 1.4)
        p.drawRoundedRect(QRectF(3, 4.5, 18, 15), 2, 2)
        _pen(p, accent, 1.7)
        p.drawLine(QPointF(6.5, 9), QPointF(9.5, 12))
        p.drawLine(QPointF(9.5, 12), QPointF(6.5, 15))
        p.drawLine(QPointF(12, 15), QPointF(17.5, 15))

    elif name == "select_all":
        _pen(p, accent, 1.3)
        p.drawRect(QRectF(4, 4, 16, 16))
        _fill(p, accent)
        for x, y in ((4, 4), (20, 4), (4, 20), (20, 20)):
            p.drawRect(QRectF(x - 1.5, y - 1.5, 3, 3))

    elif name == "deselect":
        _pen(p, "#8ea6bd", 1.3)
        p.drawRect(QRectF(4, 4, 16, 16))
        _pen(p, ORANGE, 1.7)
        p.drawLine(QPointF(7, 7), QPointF(17, 17))
        p.drawLine(QPointF(17, 7), QPointF(7, 17))

    elif name == "fit_selection":
        _pen(p, "#8ea6bd", 1.2)
        p.drawRect(QRectF(7, 7, 10, 10))
        _pen(p, accent, 1.6)
        for x, y, dx, dy in ((2, 2, 1, 1), (22, 2, -1, 1),
                              (2, 22, 1, -1), (22, 22, -1, -1)):
            p.drawLine(QPointF(x, y), QPointF(x + dx * 5, y + dy * 5))
            p.drawLine(QPointF(x + dx * 5, y), QPointF(x + dx * 5, y + dy * 5))

    elif name == "grid":
        _pen(p, accent, 1.2)
        for v in (4, 9.3, 14.6, 20):
            p.drawLine(QPointF(v, 4), QPointF(v, 20))
            p.drawLine(QPointF(4, v), QPointF(20, v))

    elif name == "diagram":
        _pen(p, "#8ea6bd", 1.2)
        p.drawLine(QPointF(3, 20.5), QPointF(21, 20.5))
        p.drawLine(QPointF(3, 3.5), QPointF(3, 20.5))
        _pen(p, accent, 1.8)
        path = QPainterPath()
        path.moveTo(4, 16)
        path.cubicTo(8, 3, 15, 3, 20.5, 16)
        p.drawPath(path)
        _fill(p, accent)
        p.drawEllipse(QPointF(20.5, 16), 1.7, 1.7)

    elif name == "pushover":
        _pen(p, "#8ea6bd", 1.2)
        p.drawLine(QPointF(3, 20.5), QPointF(21, 20.5))
        p.drawLine(QPointF(3, 3.5), QPointF(3, 20.5))
        _pen(p, accent, 1.8)
        path = QPainterPath()
        path.moveTo(4, 20)
        path.lineTo(10, 13)
        path.lineTo(13, 9)
        path.lineTo(20.5, 6)
        p.drawPath(path)
        _fill(p, ORANGE)
        p.drawEllipse(QPointF(13, 9), 2.0, 2.0)

    elif name == "hinge":
        _pen(p, "#8ea6bd", 1.4)
        p.drawLine(QPointF(3, 18), QPointF(14, 18))
        _pen(p, accent, 1.8)
        p.drawLine(QPointF(17, 18), QPointF(22, 18))
        _fill(p, ORANGE)
        p.drawEllipse(QPointF(15.5, 18), 2.4, 2.4)
        pen = QPen(QColor(accent), 1.4)
        p.setPen(pen)
        path = QPainterPath()
        path.arcMoveTo(QRectF(8, 7, 12, 12), 20)
        path.arcTo(QRectF(8, 7, 12, 12), 20, 110)
        p.drawPath(path)

    elif name == "hinge_assign":
        _pen(p, "#8ea6bd", 1.4)
        p.drawLine(QPointF(2.5, 18), QPointF(11, 18))
        _pen(p, accent, 1.8)
        p.drawLine(QPointF(14, 18), QPointF(21.5, 18))
        _fill(p, ORANGE)
        p.drawEllipse(QPointF(12.5, 18), 2.2, 2.2)
        _fill(p, accent)
        p.drawPolygon(QPolygonF([QPointF(17, 10), QPointF(23, 14),
                                  QPointF(17, 18)]))

    elif name == "deformed":
        p.setPen(QPen(QColor("#9fb0c4"), 1.3, Qt.DashLine))
        p.drawLine(QPointF(3, 17), QPointF(21, 17))
        _pen(p, ORANGE, 1.8)
        path = QPainterPath()
        path.moveTo(3, 17)
        path.cubicTo(7, 3, 17, 3, 21, 17)
        p.drawPath(path)

    elif name == "clean":
        _pen(p, accent, 1.5)
        p.drawRoundedRect(QRectF(3, 5, 18, 14), 1.5, 1.5)
        p.drawLine(QPointF(6, 17), QPointF(12, 9))
        p.drawLine(QPointF(12, 9), QPointF(18, 17))
        p.drawLine(QPointF(8, 14), QPointF(16, 14))
        _fill(p, ORANGE)
        p.drawPolygon(QPolygonF([QPointF(19, 2), QPointF(20.2, 4.8),
                                  QPointF(23, 6), QPointF(20.2, 7.2),
                                  QPointF(19, 10), QPointF(17.8, 7.2),
                                  QPointF(15, 6), QPointF(17.8, 4.8)]))

    elif name == "extruded":
        _pen(p, accent, 1.4)
        top = QPolygonF([QPointF(12, 2.5), QPointF(21, 7), QPointF(12, 11.5),
                         QPointF(3, 7)])
        left = QPolygonF([QPointF(3, 7), QPointF(12, 11.5), QPointF(12, 21.5),
                          QPointF(3, 17)])
        right = QPolygonF([QPointF(21, 7), QPointF(12, 11.5), QPointF(12, 21.5),
                           QPointF(21, 17)])
        _fill(p, "#dcebf9"); p.drawPolygon(top)
        _fill(p, "#8fb4d6"); p.drawPolygon(left)
        _fill(p, "#c5d9ec"); p.drawPolygon(right)

    elif name == "support_show":
        _pen(p, GREEN, 1.4)
        p.drawLine(QPointF(3, 21), QPointF(21, 21))
        p.drawPolygon(QPolygonF([QPointF(12, 6), QPointF(4, 20), QPointF(20, 20)]))
        _pen(p, accent, 1.3)
        p.drawEllipse(QPointF(12, 13), 5.5, 3.4)
        _fill(p, accent)
        p.drawEllipse(QPointF(12, 13), 1.7, 1.7)

    elif name == "load_show":
        _pen(p, accent, 1.6)
        p.drawLine(QPointF(7, 3), QPointF(7, 13))
        _fill(p, accent)
        _arrow_head(p, 7, 15.5, 0, 1, 2.8)
        _pen(p, ORANGE, 1.3)
        p.drawEllipse(QPointF(16, 15), 5.5, 3.4)
        _fill(p, ORANGE)
        p.drawEllipse(QPointF(16, 15), 1.7, 1.7)

    elif name in ("panel_model", "panel_props", "panel_log"):
        _pen(p, INK, 1.4)
        p.drawRoundedRect(QRectF(3, 4, 18, 16), 1.5, 1.5)
        p.drawLine(QPointF(10, 4), QPointF(10, 20))
        if name == "panel_model":
            _pen(p, accent, 1.2)
            for y in (8, 12, 16):
                p.drawLine(QPointF(5, y), QPointF(8, y))
        elif name == "panel_props":
            _pen(p, accent, 1.2)
            for y in (8.5, 13, 17.5):
                p.drawLine(QPointF(12.5, y), QPointF(18.5, y))
                p.drawEllipse(QPointF(15, y), 1.1, 1.1)
        else:
            _pen(p, accent, 1.2)
            for y in (8, 12, 16):
                p.drawLine(QPointF(12.5, y), QPointF(18.5, y))

    elif name == "help":
        _pen(p, accent, 1.5)
        p.drawEllipse(QPointF(12, 12), 9, 9)
        p.setFont(QFont("Segoe UI", 9, QFont.Bold))
        p.drawText(QPointF(8.6, 16), "?")

    elif name == "export":
        _pen(p, INK, 1.4)
        path = QPainterPath()
        path.moveTo(5, 3); path.lineTo(14, 3); path.lineTo(19, 8)
        path.lineTo(19, 21); path.lineTo(5, 21); path.closeSubpath()
        p.drawPath(path)
        _pen(p, accent, 1.6)
        p.drawLine(QPointF(12, 6), QPointF(12, 15))
        _fill(p, accent)
        _arrow_head(p, 12, 17.5, 0, 1, 2.8)

    elif name == "exit":
        _pen(p, "#8ea6bd", 1.5)
        p.drawLine(QPointF(4, 3), QPointF(4, 21))
        p.drawRect(QRectF(4, 4, 9, 16))
        _pen(p, ORANGE, 1.7)
        p.drawLine(QPointF(11, 12), QPointF(21, 12))
        _fill(p, ORANGE)
        _arrow_head(p, 22.5, 12, 1, 0, 3.0)

    elif name == "example":
        _pen(p, accent, 1.5)
        p.drawLine(QPointF(4, 20), QPointF(20, 20))
        p.drawLine(QPointF(6, 20), QPointF(6, 7))
        p.drawLine(QPointF(18, 20), QPointF(18, 7))
        p.drawLine(QPointF(6, 7), QPointF(18, 7))
        p.drawLine(QPointF(6, 14), QPointF(18, 14))

    elif name == "save_as":
        _pen(p, INK, 1.4)
        p.drawRect(QRectF(4, 3, 13, 18))
        p.drawRect(QRectF(7, 3, 7, 5))
        _pen(p, accent, 1.7)
        p.drawLine(QPointF(15, 14), QPointF(22, 14))
        p.drawLine(QPointF(22, 14), QPointF(22, 21))

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
