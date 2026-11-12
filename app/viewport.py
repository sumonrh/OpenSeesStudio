"""Interactive 3D viewport (custom software renderer, QPainter based)."""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Set, Tuple

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QBrush, QColor, QFont, QLinearGradient, QPainter,
                           QPainterPath, QPen, QPolygonF)
from PySide6.QtWidgets import QWidget

from . import theme
from .model import Project, fmt
from .opsgen import auto_vecxz, local_axes, ModalResults, StaticResults
from .units import UNITS

Vec3 = Tuple[float, float, float]


# --------------------------------------------------------------------------- #
# math helpers
# --------------------------------------------------------------------------- #
def _sub(a, b) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a, b) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _mul(a, s) -> Vec3:
    return (a[0] * s, a[1] * s, a[2] * s)


def _dot(a, b) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b) -> Vec3:
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _norm(a) -> Vec3:
    l = math.sqrt(_dot(a, a))
    return (a[0] / l, a[1] / l, a[2] / l) if l > 1e-12 else (0.0, 0.0, 0.0)


class Camera:
    def __init__(self) -> None:
        self.target = [0.0, 0.0, 0.0]
        self.distance = 8000.0
        self.yaw = math.radians(-58.0)
        self.pitch = math.radians(26.0)
        self.fov = math.radians(38.0)

    # ------------------------------------------------------------------ #
    def basis(self):
        cp, sp = math.cos(self.pitch), math.sin(self.pitch)
        d = (cp * math.cos(self.yaw), cp * math.sin(self.yaw), sp)   # target -> eye
        eye = (self.target[0] + d[0] * self.distance,
               self.target[1] + d[1] * self.distance,
               self.target[2] + d[2] * self.distance)
        f = (-d[0], -d[1], -d[2])
        r = _cross(f, (0.0, 0.0, 1.0))
        if _dot(r, r) < 1e-9:
            r = (1.0, 0.0, 0.0)
        r = _norm(r)
        u = _cross(r, f)
        return eye, f, r, u

    def project(self, p: Vec3, w: int, h: int):
        eye, f, r, u = self.basis()
        d = _sub(p, eye)
        z = _dot(d, f)
        if z < 1e-6:
            return None
        focal = 0.5 * h / math.tan(self.fov / 2.0)
        sx = 0.5 * w + focal * _dot(d, r) / z
        sy = 0.5 * h - focal * _dot(d, u) / z
        return sx, sy, z

    def world_per_pixel(self, h: int) -> float:
        return 2.0 * math.tan(self.fov / 2.0) * self.distance / max(h, 1)

    def fit(self, points: Sequence[Vec3], aspect: float = 1.0) -> None:
        if not points:
            self.target = [0.0, 0.0, 0.0]
            self.distance = 8000.0
            return
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        zs = [p[2] for p in points]
        c = [(min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, (min(zs) + max(zs)) / 2]
        radius = max(0.5 * math.dist((min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))), 1.0)
        self.target = c
        f = math.tan(self.fov / 2.0)
        dist_v = radius / f
        dist_h = radius / (f * max(aspect, 1e-3))
        self.distance = max(dist_v, dist_h) * 1.35


# --------------------------------------------------------------------------- #
# viewport widget
# --------------------------------------------------------------------------- #
class Viewport(QWidget):
    selectionChanged = Signal()
    statusMessage = Signal(str)
    cameraChanged = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(420, 300)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.ArrowCursor)

        self.project: Optional[Project] = None
        self.camera = Camera()

        self.sel_nodes: Set[int] = set()
        self.sel_elements: Set[int] = set()

        self.show_nodes = True
        self.show_elements = True
        self.show_supports = True
        self.show_loads = True
        self.show_labels = False
        self.show_grid = True
        self.show_axes = True
        self.wireframe = True
        self.orbit_mode = False
        self.show_extruded = False

        self.static_results: Optional[StaticResults] = None
        self.modal_results: Optional[ModalResults] = None
        self.mode_index = 1
        self.show_deformed = True
        self.deformed_scale: Optional[float] = None
        self.load_scenario: str = ""

        self._band: Optional[QRect] = None
        self._press: Optional[QPoint] = None
        self._panning = False
        self._orbiting = False
        self._last = QPoint()
        self._hover_node: Optional[int] = None
        self._hover_elem: Optional[int] = None
        self._moved = False

        self._anim_phase = 0.0
        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(40)
        self._anim_timer.timeout.connect(self._tick)

    # ------------------------------------------------------------------ data
    def set_project(self, project: Project, fit: bool = True) -> None:
        self.project = project
        self.sel_nodes.clear()
        self.sel_elements.clear()
        self.static_results = None
        self.modal_results = None
        if fit:
            self.fit()
        self.selectionChanged.emit()
        self.update()

    def set_static_results(self, res: Optional[StaticResults]) -> None:
        self.static_results = res
        self.modal_results = None
        self.deformed_scale = None
        self.update()

    def set_modal_results(self, res: Optional[ModalResults], mode: int = 1) -> None:
        self.modal_results = res
        self.static_results = None
        self.mode_index = mode
        self.deformed_scale = None
        self.update()

    def clear_results(self) -> None:
        self.static_results = None
        self.modal_results = None
        self.stop_animation()
        self.update()

    # ------------------------------------------------------------- selection
    def clear_selection(self) -> None:
        self.sel_nodes.clear()
        self.sel_elements.clear()
        self.selectionChanged.emit()
        self.update()

    def select_all(self) -> None:
        if self.project:
            self.sel_nodes = set(self.project.nodes)
            self.sel_elements = set(self.project.elements)
            self.selectionChanged.emit()
            self.update()

    def select_nodes(self, tags: Sequence[int], additive: bool = False) -> None:
        if not additive:
            self.sel_nodes.clear()
            self.sel_elements.clear()
        self.sel_nodes.update(tags)
        self.selectionChanged.emit()
        self.update()

    def select_elements(self, tags: Sequence[int], additive: bool = False) -> None:
        if not additive:
            self.sel_nodes.clear()
            self.sel_elements.clear()
        self.sel_elements.update(tags)
        self.selectionChanged.emit()
        self.update()

    # ------------------------------------------------------------------ view
    def fit(self) -> None:
        if not self.project:
            return
        pts = [n.xyz for n in self.project.nodes.values()] or [(0, 0, 0), (1000, 0, 0)]
        aspect = max(self.width(), 200) / max(self.height(), 150)
        self.camera.fit(pts, aspect)
        self.cameraChanged.emit()
        self.update()

    def fit_selection(self) -> None:
        if not self.project:
            return
        pts = [self.project.nodes[t].xyz for t in self.sel_nodes if t in self.project.nodes]
        for t in self.sel_elements:
            e = self.project.elements.get(t)
            if e:
                pts += [self.project.node_xyz(i) for i in e.nodes]
        if pts:
            aspect = max(self.width(), 200) / max(self.height(), 150)
            self.camera.fit(pts, aspect)
            self.cameraChanged.emit()
            self.update()

    def set_view(self, name: str) -> None:
        presets = {
            "iso": (-58.0, 26.0),
            "top": (-90.0, 89.0),
            "bottom": (-90.0, -89.0),
            "front": (-90.0, 0.0),
            "back": (90.0, 0.0),
            "left": (180.0, 0.0),
            "right": (0.0, 0.0),
        }
        yaw, pitch = presets.get(name, presets["iso"])
        self.camera.yaw = math.radians(yaw)
        self.camera.pitch = math.radians(pitch)
        self.cameraChanged.emit()
        self.update()

    def zoom(self, factor: float) -> None:
        self.camera.distance = min(max(self.camera.distance / factor, 0.1), 1e12)
        self.cameraChanged.emit()
        self.update()

    def set_show(self, **kwargs) -> None:
        for k, v in kwargs.items():
            if hasattr(self, k):
                setattr(self, k, bool(v))
        self.update()

    def set_orbit_mode(self, on: bool) -> None:
        """AutoCAD-style 3D orbit: left-drag rotates instead of selecting."""
        self.orbit_mode = bool(on)
        self.setCursor(Qt.OpenHandCursor if self.orbit_mode else Qt.ArrowCursor)
        self.statusMessage.emit("Orbit mode: drag to rotate   (Esc to exit)"
                                if self.orbit_mode else "Orbit mode off")
        self.update()

    # ---------------------------------------------------------- deformation
    def _display_scale(self) -> float:
        if self.deformed_scale is not None and self.deformed_scale > 0:
            return self.deformed_scale
        if not self.project:
            return 1.0
        (x0, y0, z0), (x1, y1, z1) = self.project.bbox()
        diag = max(math.dist((x0, y0, z0), (x1, y1, z1)), 1.0)
        peak = 0.0
        if self.static_results:
            peak = max((max(abs(v) for v in d) for d in self.static_results.displacements.values()),
                       default=0.0)
        elif self.modal_results:
            peak = 1.0
        if peak <= 0:
            return 1.0
        return 0.07 * diag / peak

    def _disp_of(self, node: int) -> List[float]:
        if self.modal_results:
            shape = self.modal_results.shapes.get(self.mode_index, {})
            d = shape.get(node, [0.0] * 6)
            phase = math.sin(self._anim_phase) if self._anim_timer.isActive() else 1.0
            return [v * phase for v in d]
        if self.static_results:
            return self.static_results.displacements.get(node, [0.0] * 6)
        return [0.0] * 6

    def _deformed_points(self) -> Dict[int, Vec3]:
        if not self.project or not (self.static_results or self.modal_results):
            return {}
        s = self._display_scale()
        out: Dict[int, Vec3] = {}
        for tag, n in self.project.nodes.items():
            d = self._disp_of(tag)
            out[tag] = (n.x + s * d[0], n.y + s * d[1], n.z + s * d[2])
        return out

    def start_animation(self) -> None:
        if self.modal_results:
            self.show_deformed = True
            self._anim_timer.start()

    def stop_animation(self) -> None:
        self._anim_timer.stop()
        self._anim_phase = 0.0
        self.update()

    def is_animating(self) -> bool:
        return self._anim_timer.isActive()

    def _tick(self) -> None:
        self._anim_phase += 0.09
        self.update()

    # ----------------------------------------------------------------- paint
    def paintEvent(self, ev) -> None:
        w, h = self.width(), self.height()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)

        grad = QLinearGradient(0, 0, 0, h)
        grad.setColorAt(0.0, theme.VIEW_TOP)
        grad.setColorAt(1.0, theme.VIEW_BOTTOM)
        p.fillRect(self.rect(), QBrush(grad))

        if not self.project or not self.project.nodes:
            p.setPen(QPen(QColor(theme.MUTED)))
            f = QFont("Segoe UI", 11)
            p.setFont(f)
            p.drawText(self.rect(), Qt.AlignCenter,
                       "Empty model\n\nStructure  >  New Node...   (or press N)")
            p.end()
            return

        if self.show_grid:
            self._draw_grid(p, w, h)

        cam = self.camera
        proj = {}
        for tag, n in self.project.nodes.items():
            s = cam.project(n.xyz, w, h)
            if s:
                proj[tag] = s

        deformed = self._deformed_points()
        dproj = {}
        if deformed and self.show_deformed:
            for tag, xyz in deformed.items():
                s = cam.project(xyz, w, h)
                if s:
                    dproj[tag] = s

        # ---- elements --------------------------------------------------
        if self.show_extruded:
            self._draw_extruded(p, w, h)
        else:
            items = []
            for tag, e in self.project.elements.items():
                pts = [proj.get(t) for t in e.nodes]
                if any(s is None for s in pts):
                    continue
                depth = sum(s[2] for s in pts) / len(pts)
                items.append((depth, tag, e, pts))
            items.sort(key=lambda x: -x[0])

            for depth, tag, e, pts in items:
                selected = tag in self.sel_elements
                base = {"beam": theme.ELEM_BEAM, "truss": theme.ELEM_TRUSS,
                        "shell": theme.ELEM_SHELL}.get(e.kind, theme.ELEM_BEAM)
                if selected:
                    pen = QPen(theme.SELECTED, 3.4)
                elif self.show_deformed and dproj:
                    pen = QPen(QColor("#c3cdd9"), 1.2, Qt.DashLine)
                else:
                    pen = QPen(base, 2.6 if e.kind == "beam" else 1.9)
                p.setPen(pen)
                poly = QPolygonF([QPointF(s[0], s[1]) for s in pts])
                if e.kind == "shell" and len(pts) >= 4:
                    p.setBrush(QBrush(QColor(113, 136, 165, 28)))
                    p.drawPolygon(poly)
                    p.setBrush(Qt.NoBrush)
                else:
                    p.drawPolyline(poly)
                if not self.show_elements:
                    continue

        # ---- deformed shape -------------------------------------------
        if dproj and self.show_deformed and not self.show_extruded:
            items2 = []
            for tag, e in self.project.elements.items():
                pts = [dproj.get(t) for t in e.nodes]
                if any(s is None for s in pts):
                    continue
                items2.append((sum(s[2] for s in pts) / len(pts), tag, e, pts))
            items2.sort(key=lambda x: -x[0])
            for depth, tag, e, pts in items2:
                p.setPen(QPen(theme.DEFORMED, 2.8 if e.kind == "beam" else 2.0))
                p.drawPolyline(QPolygonF([QPointF(s[0], s[1]) for s in pts]))

        # ---- loads -----------------------------------------------------
        if self.show_loads:
            self._draw_loads(p, w, h, proj)

        # ---- supports --------------------------------------------------
        if self.show_supports:
            for tag, n in self.project.nodes.items():
                if not any(n.support):
                    continue
                s = proj.get(tag)
                if not s:
                    continue
                self._draw_support(p, s[0], s[1], all(n.support))

        # ---- nodes -----------------------------------------------------
        if self.show_nodes:
            nodes_sorted = sorted(proj.items(), key=lambda kv: -kv[1][2])
            for tag, s in nodes_sorted:
                selected = tag in self.sel_nodes
                hover = tag == self._hover_node
                r = 5.2 if selected else (4.6 if hover else 3.9)
                if self.show_extruded:
                    r = 4.2 if selected else (3.2 if hover else 1.8)
                if selected:
                    p.setBrush(QBrush(theme.SELECTED))
                    p.setPen(QPen(QColor("#ffffff"), 1.6))
                else:
                    p.setBrush(QBrush(QColor("#ffffff") if hover else theme.NODE_COLOR))
                    p.setPen(QPen(QColor(theme.NODE_COLOR), 1.4 if hover else 1.2))
                p.drawEllipse(QPointF(s[0], s[1]), r, r)

        # ---- labels ----------------------------------------------------
        if self.show_labels:
            p.setFont(QFont("Segoe UI", 7))
            p.setPen(QPen(QColor("#41566e")))
            for tag, s in proj.items():
                if len(proj) > 900:
                    break
                p.drawText(QPointF(s[0] + 6, s[1] - 5), str(tag))
            if len(self.project.elements) <= 600:
                p.setPen(QPen(QColor("#7b8ea3")))
                for tag, e in self.project.elements.items():
                    pts = [proj.get(t) for t in e.nodes]
                    if any(s is None for s in pts) or not pts:
                        continue
                    mx = sum(s[0] for s in pts) / len(pts)
                    my = sum(s[1] for s in pts) / len(pts)
                    p.drawText(QPointF(mx + 3, my + 12), str(tag))

        # ---- triad, HUD, band -----------------------------------------
        if self.show_axes:
            self._draw_triad(p, w, h)
        self._draw_hud(p, w, h)
        if self._band is not None:
            p.setPen(QPen(QColor(theme.ACCENT), 1.2, Qt.DashLine))
            p.setBrush(QBrush(QColor(15, 111, 184, 28)))
            p.drawRect(self._band.normalized())
        p.end()

    # ------------------------------------------------------------- paint bits
    def _draw_extruded(self, p: QPainter, w: int, h: int) -> None:
        """Draw beam members as extruded solids using their section sizes."""
        if not self.project or not self.project.elements:
            return
        cam = self.camera
        deformed = self._deformed_points()
        pts3 = deformed if (self.show_deformed and deformed) else \
            {tag: n.xyz for tag, n in self.project.nodes.items()}

        items = []
        for tag, e in self.project.elements.items():
            base = [pts3.get(t) for t in e.nodes]
            if any(pt is None for pt in base):
                continue
            screen = [cam.project(pt, w, h) for pt in base]
            if any(s is None for s in screen):
                continue
            depth = sum(s[2] for s in screen) / len(screen)
            items.append((depth, tag, e, base, screen))
        items.sort(key=lambda x: -x[0])

        for _depth, tag, e, base, screen in items:
            selected = tag in self.sel_elements
            hover = tag == self._hover_elem
            color = QColor(theme.SELECTED if selected else
                           (theme.ACCENT if hover else theme.ELEM_BEAM))
            if e.kind == "shell" and len(screen) >= 4:
                p.setPen(QPen(color, 2.2 if selected else 1.4))
                p.setBrush(QBrush(QColor(color.red(), color.green(), color.blue(), 55)))
                p.drawPolygon(QPolygonF([QPointF(s[0], s[1]) for s in screen]))
                p.setBrush(Qt.NoBrush)
                continue
            if e.kind != "beam" or len(base) < 2:
                p.setPen(QPen(color, 3.4 if selected else 2.0))
                p.drawPolyline(QPolygonF([QPointF(s[0], s[1]) for s in screen]))
                continue

            p0, p1 = base[0], base[1]
            if math.dist(p0, p1) < 1e-6:
                continue
            vec = e.vecxz or auto_vecxz(p0, p1)
            axes = local_axes(p0, p1, vec)
            if axes is None:
                continue
            _x, uy, uz = axes
            outer, inner = _section_profiles(self.project.section_of(e))

            def offset_point(pt, oy, oz):
                return (pt[0] + oy * uy[0] + oz * uz[0],
                        pt[1] + oy * uy[1] + oz * uz[1],
                        pt[2] + oy * uy[2] + oz * uz[2])

            def project_profile(pt, profile):
                out = []
                for oy, oz in profile:
                    s = cam.project(offset_point(pt, oy, oz), w, h)
                    if s is None:
                        return None
                    out.append(s)
                return out

            ep0 = project_profile(p0, outer)
            ep1 = project_profile(p1, outer)
            if not ep0 or not ep1:
                continue

            fill = QColor(color.red(), color.green(), color.blue(),
                          34 if selected else 16)
            for i in range(len(ep0)):
                j = (i + 1) % len(ep0)
                side = QPolygonF([QPointF(ep0[i][0], ep0[i][1]),
                                  QPointF(ep0[j][0], ep0[j][1]),
                                  QPointF(ep1[j][0], ep1[j][1]),
                                  QPointF(ep1[i][0], ep1[i][1])])
                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(fill))
                p.drawPolygon(side)

            p.setPen(QPen(color, 1.7 if selected else 1.0))
            p.setBrush(QBrush(QColor(color.red(), color.green(), color.blue(),
                                     46 if selected else 28)))
            p.drawPolygon(QPolygonF([QPointF(s[0], s[1]) for s in ep0]))
            p.drawPolygon(QPolygonF([QPointF(s[0], s[1]) for s in ep1]))
            p.setBrush(Qt.NoBrush)

            p.setPen(QPen(color, 1.15 if selected else 0.8))
            for i in range(len(ep0)):
                p.drawLine(QPointF(ep0[i][0], ep0[i][1]),
                           QPointF(ep1[i][0], ep1[i][1]))

            if inner:
                ip0 = project_profile(p0, inner)
                ip1 = project_profile(p1, inner)
                if ip0 and ip1:
                    p.setPen(QPen(QColor(255, 255, 255, 190), 0.9))
                    p.drawPolygon(QPolygonF([QPointF(s[0], s[1]) for s in ip0]))
                    p.drawPolygon(QPolygonF([QPointF(s[0], s[1]) for s in ip1]))
                    for i in range(len(ip0)):
                        p.drawLine(QPointF(ip0[i][0], ip0[i][1]),
                                   QPointF(ip1[i][0], ip1[i][1]))

    def _draw_grid(self, p: QPainter, w: int, h: int) -> None:
        ext = self.camera.distance * math.tan(self.camera.fov / 2) * 1.25
        step = _nice_step(ext / 7.0)
        cx, cy = self.camera.target[0], self.camera.target[1]
        n = int(ext / step) + 1
        p.setRenderHint(QPainter.Antialiasing, False)
        for i in range(-n, n + 1):
            major = abs(i) % 5 == 0
            p.setPen(QPen(theme.GRID_MAJOR if major else theme.GRID_MINOR, 1.0))
            x = cx + i * step
            a = self.camera.project((x, cy - n * step, 0), w, h)
            b = self.camera.project((x, cy + n * step, 0), w, h)
            if a and b:
                p.drawLine(QPointF(a[0], a[1]), QPointF(b[0], b[1]))
            y = cy + i * step
            a = self.camera.project((cx - n * step, y, 0), w, h)
            b = self.camera.project((cx + n * step, y, 0), w, h)
            if a and b:
                p.drawLine(QPointF(a[0], a[1]), QPointF(b[0], b[1]))
        p.setRenderHint(QPainter.Antialiasing, True)

    def _draw_support(self, p: QPainter, sx: float, sy: float, full: bool) -> None:
        p.setPen(QPen(QColor("#ffffff"), 1.2))
        p.setBrush(QBrush(theme.SUPPORT_COLOR))
        if full:
            p.drawRect(QRectF(sx - 4.5, sy + 2.5, 9, 9))
        else:
            p.drawPolygon(QPolygonF([QPointF(sx, sy + 3), QPointF(sx - 5.5, sy + 11),
                                     QPointF(sx + 5.5, sy + 11)]))

    def _draw_triad(self, p: QPainter, w: int, h: int) -> None:
        ox, oy = 62.0, h - 56.0
        _eye, _f, r, u = self.camera.basis()
        axes = [("X", (1, 0, 0), theme.AXIS_X),
                ("Y", (0, 1, 0), theme.AXIS_Y),
                ("Z", (0, 0, 1), theme.AXIS_Z)]
        p.setFont(QFont("Segoe UI", 7, QFont.Bold))
        for label, a, color in axes:
            dx = _dot(a, r) * 34
            dy = -_dot(a, u) * 34
            p.setPen(QPen(color, 2.0))
            p.drawLine(QPointF(ox, oy), QPointF(ox + dx, oy + dy))
            p.setBrush(QBrush(color))
            p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(ox + dx, oy + dy), 2.0, 2.0)
            p.setPen(QPen(color))
            p.drawText(QPointF(ox + dx * 1.22 - 3, oy + dy * 1.22 + 4), label)

    def _draw_hud(self, p: QPainter, w: int, h: int) -> None:
        lines = [f"Nodes {len(self.project.nodes)}   Elements {len(self.project.elements)}"]
        if self.show_extruded:
            lines.append("Extruded sections")
        if self.static_results:
            sc = self._display_scale()
            lines.append(f"Case: {self.static_results.scenario}    Deformed shape ×{sc:,.1f}")
        elif self.modal_results and self.modal_results.modes:
            m = self.modal_results.modes[min(self.mode_index - 1, len(self.modal_results.modes) - 1)]
            lines.append(f"Mode {self.mode_index}    T = {m.period:.4f} s    f = {m.frequency:.4f} Hz")
        p.setFont(QFont("Segoe UI", 8))
        fm = p.fontMetrics()
        bw = max(fm.horizontalAdvance(s) for s in lines) + 18
        bh = 10 + len(lines) * (fm.height() + 2) + 4
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor(255, 255, 255, 214)))
        p.drawRoundedRect(QRectF(10, 10, bw, bh), 4, 4)
        p.setPen(QPen(QColor("#4a617a")))
        y = 24
        for s in lines:
            p.drawText(QPointF(19, y), s)
            y += fm.height() + 2

    # --------------------------------------------------------------- loads
    def _draw_loads(self, p: QPainter, w: int, h: int, proj) -> None:
        if not self.project or not self.load_scenario:
            return
        proj_ = self.project
        case_map = {c: f for c, f in _scenario_cases(proj_, self.load_scenario)}
        if not case_map:
            return

        # nodal loads
        arrows = []
        peak_f = 0.0
        for nl in proj_.nodal_loads:
            if nl.case not in case_map:
                continue
            f = [v * case_map[nl.case] for v in nl.values]
            mag = math.sqrt(sum(v * v for v in f[:3]))
            peak_f = max(peak_f, mag)
            if mag > 0:
                arrows.append((nl.node, f))
        if peak_f > 0:
            for node, f in arrows:
                s = proj.get(node)
                if not s:
                    continue
                sx, sy = s[0], s[1]
                mag = math.sqrt(sum(v * v for v in f[:3]))
                length = 26 + 26 * (mag / peak_f)
                _eye, _f, r, u = self.camera.basis()
                d = (f[0], f[1], f[2])
                vx = _dot(d, r)
                vy = -_dot(d, u)
                norm = math.hypot(vx, vy)
                if norm < 1e-9:
                    continue
                vx, vy = vx / norm, vy / norm
                x0 = sx - vx * length
                y0 = sy - vy * length
                p.setPen(QPen(theme.LOAD_COLOR, 1.8))
                p.drawLine(QPointF(x0, y0), QPointF(sx, sy))
                self._head(p, sx, sy, vx, vy, 6.0, theme.LOAD_COLOR)
                p.setFont(QFont("Segoe UI", 7))
                p.setPen(QPen(QColor(theme.ACCENT_DARK)))
                p.drawText(QPointF(x0 - 2, y0 - 4), fmt(UNITS.force(mag), 1))
            # moments
            for nl in proj_.nodal_loads:
                if nl.case not in case_map:
                    continue
                f = [v * case_map[nl.case] for v in nl.values]
                if max(abs(v) for v in f[3:]) > 0:
                    s = proj.get(nl.node)
                    if not s:
                        continue
                    p.setPen(QPen(theme.LOAD_COLOR, 1.5))
                    p.setBrush(Qt.NoBrush)
                    p.drawArc(QRectF(s[0] - 9, s[1] - 9, 18, 18), 30 * 16, 300 * 16)
                    self._head(p, s[0] + 7, s[1] - 5, 1, -1, 4.5, theme.LOAD_COLOR)

        # element loads
        for el in proj_.elem_loads:
            if el.case not in case_map:
                continue
            e = proj_.elements.get(el.elem)
            if not e or len(e.nodes) < 2:
                continue
            pts = [proj.get(t) for t in e.nodes[:2]]
            if any(s is None for s in pts):
                continue
            fac = case_map[el.case]
            p0 = proj_.node_xyz(e.nodes[0])
            p1 = proj_.node_xyz(e.nodes[1])
            if el.kind == "point":
                world_dir = _load_world_dir(proj_, e, el.direction)
                if world_dir is None:
                    continue
                base = _lerp(p0, p1, el.position)
                s = self.camera.project(base, w, h)
                if not s:
                    continue
                _eye, _f, r, u = self.camera.basis()
                vx = _dot(world_dir, r)
                vy = -_dot(world_dir, u)
                norm = math.hypot(vx, vy)
                if norm < 1e-9:
                    continue
                vx, vy = vx / norm, vy / norm
                ln = 30.0
                p.setPen(QPen(theme.LOAD_COLOR, 1.8))
                p.drawLine(QPointF(s[0] - vx * ln, s[1] - vy * ln), QPointF(s[0], s[1]))
                self._head(p, s[0], s[1], vx, vy, 5.0, theme.LOAD_COLOR)
                p.setFont(QFont("Segoe UI", 7))
                p.setPen(QPen(QColor(theme.ACCENT_DARK)))
                p.drawText(QPointF(s[0] + 6, s[1] - 6), fmt(UNITS.force(el.value * fac), 1))
            else:
                world_dir = _load_world_dir(proj_, e, el.direction)
                if world_dir is None:
                    continue
                self._dist_arrows(p, proj_, e, proj_, world_dir, el.value * fac, None,
                                  trapezoid=el.trapezoid, value2=el.value2 * fac)

    def _dist_arrows(self, p, proj_, e, proj, world_dir, value, anchor,
                     trapezoid=False, value2=0.0) -> None:
        n = 5
        p0 = proj_.node_xyz(e.nodes[0])
        p1 = proj_.node_xyz(e.nodes[1])
        scale = 0.06 * max(math.dist(p0, p1), 1.0)
        _eye, _f, r, u = self.camera.basis()
        vx = _dot(world_dir, r)
        vy = -_dot(world_dir, u)
        norm = math.hypot(vx, vy)
        if norm < 1e-9:
            return
        vx, vy = vx / norm, vy / norm
        color = QColor(15, 111, 184, 150)
        for i in range(n):
            xL = (i + 0.5) / n
            wv = value + (value2 - value) * xL if trapezoid else value
            base = _add(p0, _mul(_sub(p1, p0), xL))
            s = self.camera.project(base, self.width(), self.height())
            if not s:
                continue
            ln = min(scale * abs(wv) / max(abs(value), abs(value2), 1e-9) * 1.5, 26)
            x0, y0 = s[0] - vx * ln, s[1] - vy * ln
            p.setPen(QPen(color, 1.1))
            p.drawLine(QPointF(x0, y0), QPointF(s[0], s[1]))
            self._head(p, s[0], s[1], vx, vy, 3.4, color)
        # connecting line
        a = self.camera.project(p0, self.width(), self.height())
        b = self.camera.project(p1, self.width(), self.height())
        if a and b:
            p.setPen(QPen(QColor(15, 111, 184, 90), 1.0, Qt.DotLine))
            p.drawLine(QPointF(a[0], a[1]), QPointF(b[0], b[1]))

    @staticmethod
    def _head(p, x, y, vx, vy, size, color) -> None:
        ang = math.atan2(vy, vx)
        a1, a2 = ang + 2.6, ang - 2.6
        pts = [QPointF(x, y),
               QPointF(x - size * math.cos(a1), y - size * math.sin(a1)),
               QPointF(x - size * math.cos(a2), y - size * math.sin(a2))]
        p.setBrush(QBrush(color))
        p.setPen(Qt.NoPen)
        p.drawPolygon(QPolygonF(pts))
        p.setBrush(Qt.NoBrush)

    # --------------------------------------------------------------- picking
    def _hit(self, pos: QPoint):
        if not self.project:
            return None, None
        w, h = self.width(), self.height()
        best_node, best_nd = None, 9.0
        for tag, n in self.project.nodes.items():
            s = self.camera.project(n.xyz, w, h)
            if not s:
                continue
            d = math.hypot(s[0] - pos.x(), s[1] - pos.y())
            if d < best_nd:
                best_node, best_nd = tag, d
        if best_node is not None:
            return best_node, None
        best_elem, best_ed = None, 7.0
        for tag, e in self.project.elements.items():
            pts = [self.camera.project(self.project.node_xyz(t), w, h) for t in e.nodes]
            if any(s is None for s in pts):
                continue
            for a, b in zip(pts, pts[1:]):
                d = _point_segment_distance(pos.x(), pos.y(), a[0], a[1], b[0], b[1])
                if d < best_ed:
                    best_elem, best_ed = tag, d
        return None, best_elem

    def _rubber_select(self, rect: QRect, additive: bool) -> None:
        if not self.project:
            return
        w, h = self.width(), self.height()
        if not additive:
            self.sel_nodes.clear()
            self.sel_elements.clear()
        for tag, n in self.project.nodes.items():
            s = self.camera.project(n.xyz, w, h)
            if s and rect.contains(QPoint(int(s[0]), int(s[1]))):
                self.sel_nodes.add(tag)
        for tag, e in self.project.elements.items():
            pts = [self.camera.project(self.project.node_xyz(t), w, h) for t in e.nodes]
            if any(s is None for s in pts):
                continue
            mx = sum(s[0] for s in pts) / len(pts)
            my = sum(s[1] for s in pts) / len(pts)
            if rect.contains(QPoint(int(mx), int(my))):
                self.sel_elements.add(tag)
        self.selectionChanged.emit()
        self.update()

    # ---------------------------------------------------------------- events
    def mousePressEvent(self, ev) -> None:
        self.setFocus()
        self._press = ev.position().toPoint()
        self._last = self._press
        self._moved = False
        if ev.button() == Qt.LeftButton:
            if self.orbit_mode or bool(ev.modifiers() & Qt.ShiftModifier):
                self._orbiting = True
                self.setCursor(Qt.ClosedHandCursor)
            else:
                self._band = QRect(self._press, self._press)
        elif ev.button() == Qt.MiddleButton:
            if bool(ev.modifiers() & Qt.ShiftModifier):     # AutoCAD-style orbit
                self._orbiting = True
                self.setCursor(Qt.ClosedHandCursor)
            else:
                self._panning = True
                self.setCursor(Qt.ClosedHandCursor)
        elif ev.button() == Qt.RightButton:
            self._orbiting = True
            self.setCursor(Qt.SizeAllCursor)
        self.update()

    def mouseMoveEvent(self, ev) -> None:
        pos = ev.position().toPoint()
        if self._press is not None and (pos - self._press).manhattanLength() > 3:
            self._moved = True
        if self._band is not None:
            self._band = QRect(self._press, pos)
            self.update()
            return
        if self._panning:
            dx = pos.x() - self._last.x()
            dy = pos.y() - self._last.y()
            scale = self.camera.world_per_pixel(self.height())
            _eye, _f, r, u = self.camera.basis()
            self.camera.target[0] -= (r[0] * dx - u[0] * dy) * scale
            self.camera.target[1] -= (r[1] * dx - u[1] * dy) * scale
            self.camera.target[2] -= (r[2] * dx - u[2] * dy) * scale
            self._last = pos
            self.update()
            return
        if self._orbiting:
            dx = pos.x() - self._last.x()
            dy = pos.y() - self._last.y()
            self.camera.yaw -= dx * 0.008
            self.camera.pitch = max(-math.radians(89.5),
                                    min(math.radians(89.5), self.camera.pitch + dy * 0.008))
            self._last = pos
            self.update()
            return
        if self.orbit_mode:
            self.setCursor(Qt.OpenHandCursor)
            return

        node, elem = self._hit(pos)
        if node != self._hover_node or elem != self._hover_elem:
            self._hover_node, self._hover_elem = node, elem
            self.setCursor(Qt.PointingHandCursor if (node or elem) else Qt.ArrowCursor)
            self.update()
            if node:
                n = self.project.nodes[node]
                self.statusMessage.emit(f"Node {node}   ({fmt(UNITS.length(n.x), 1)}, "
                                        f"{fmt(UNITS.length(n.y), 1)}, "
                                        f"{fmt(UNITS.length(n.z), 1)}) {UNITS.length_unit}   "
                                        f"support {n.support_code()}")
            elif elem:
                e = self.project.elements[elem]
                self.statusMessage.emit(f"Element {elem}   {e.kind}   nodes {e.nodes}")

    def mouseReleaseEvent(self, ev) -> None:
        if self._band is not None:
            rect = self._band.normalized()
            self._band = None
            additive = bool(ev.modifiers() & Qt.ControlModifier)
            if self._moved and rect.width() > 4 and rect.height() > 4:
                self._rubber_select(rect, additive)
            else:
                node, elem = self._hit(ev.position().toPoint())
                if not additive:
                    self.sel_nodes.clear()
                    self.sel_elements.clear()
                if node is not None:
                    if additive and node in self.sel_nodes:
                        self.sel_nodes.discard(node)
                    else:
                        self.sel_nodes.add(node)
                elif elem is not None:
                    if additive and elem in self.sel_elements:
                        self.sel_elements.discard(elem)
                    else:
                        self.sel_elements.add(elem)
                self.selectionChanged.emit()
            self.update()
        self._panning = False
        self._orbiting = False
        self._press = None
        self._moved = False
        self.setCursor(Qt.OpenHandCursor if self.orbit_mode else Qt.ArrowCursor)
        self.update()

    def wheelEvent(self, ev) -> None:
        steps = ev.angleDelta().y() / 120.0
        factor = math.pow(1.18, steps)
        # zoom towards cursor
        pos = ev.position().toPoint()
        self.zoom(factor)
        ev.accept()

    def keyPressEvent(self, ev) -> None:
        if ev.key() == Qt.Key_Escape:
            if self.orbit_mode:
                self.set_orbit_mode(False)
            else:
                self.clear_selection()
        elif ev.key() == Qt.Key_F:
            self.fit()
        else:
            super().keyPressEvent(ev)


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #
def _lerp(a, b, t):
    return (a[0] + (b[0] - a[0]) * t,
            a[1] + (b[1] - a[1]) * t,
            a[2] + (b[2] - a[2]) * t)


def _nice_step(x: float) -> float:
    if x <= 0:
        return 1.0
    e = math.floor(math.log10(x))
    base = 10 ** e
    for m in (1, 2, 5, 10):
        if x <= m * base:
            return m * base
    return 10 * base


def _section_profiles(sec) -> list:
    """Return (outer, inner) cross-section outlines in local (y, z) mm."""
    shape = getattr(sec, "shape", "Rectangle")
    b = max(float(getattr(sec, "b", 300.0) or 300.0), 1.0)
    h = max(float(getattr(sec, "h", 600.0) or 600.0), 1.0)
    d = max(float(getattr(sec, "d", 400.0) or 400.0), 1.0)
    t = max(float(getattr(sec, "t", 0.0) or 0.0), 0.0)
    tw = max(float(getattr(sec, "tw", 0.0) or 0.0), 1.0)
    tf = max(float(getattr(sec, "tf", 0.0) or 0.0), 1.0)

    if shape == "Circle":
        pts = [(0.5 * d * math.cos(a), 0.5 * d * math.sin(a))
               for a in [i * 2 * math.pi / 16 for i in range(16)]]
        return [pts, None]

    if shape == "Pipe":
        ro = 0.5 * d
        ri = max(ro - t, 0.0)
        outer = [(ro * math.cos(a), ro * math.sin(a))
                 for a in [i * 2 * math.pi / 16 for i in range(16)]]
        inner = [(ri * math.cos(a), ri * math.sin(a))
                 for a in [i * 2 * math.pi / 16 for i in range(16)]] if ri > 1 else None
        return [outer, inner]

    if shape == "I-Shape":
        tw = min(tw, b)
        tf = min(tf, 0.49 * h)
        outer = [(-b / 2, h / 2), (b / 2, h / 2), (b / 2, h / 2 - tf),
                 (tw / 2, h / 2 - tf), (tw / 2, -h / 2 + tf), (b / 2, -h / 2 + tf),
                 (b / 2, -h / 2), (-b / 2, -h / 2), (-b / 2, -h / 2 + tf),
                 (-tw / 2, -h / 2 + tf), (-tw / 2, h / 2 - tf), (-b / 2, h / 2 - tf)]
        return [outer, None]

    if shape == "Box":
        outer = [(-b / 2, -h / 2), (b / 2, -h / 2), (b / 2, h / 2), (-b / 2, h / 2)]
        bi, hi = b - 2 * t, h - 2 * t
        inner = ([(-bi / 2, -hi / 2), (bi / 2, -hi / 2),
                  (bi / 2, hi / 2), (-bi / 2, hi / 2)] if bi > 1 and hi > 1 else None)
        return [outer, inner]

    if shape == "User" and float(getattr(sec, "A", 0.0) or 0.0) > 0:
        side = math.sqrt(float(sec.A))
        b = h = max(side, 1.0)

    return [[(-b / 2, -h / 2), (b / 2, -h / 2), (b / 2, h / 2), (-b / 2, h / 2)], None]


def _point_segment_distance(px, py, x0, y0, x1, y1) -> float:
    dx, dy = x1 - x0, y1 - y0
    if dx == 0 and dy == 0:
        return math.hypot(px - x0, py - y0)
    t = ((px - x0) * dx + (py - y0) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    return math.hypot(px - (x0 + t * dx), py - (y0 + t * dy))


def _scenario_cases(project: Project, scenario: str):
    combo = project.combos.get(scenario)
    if combo is not None:
        return [(c, f) for c, f in combo.factors]
    return [(scenario, 1.0)]


def _load_world_dir(project: Project, e, direction: str):
    if direction == "local-y" or direction == "local-z":
        p = project.node_xyz(e.nodes[0])
        q = project.node_xyz(e.nodes[1])
        _x, y, z = local_axes(p, q, e.vecxz or auto_vecxz(p, q))
        return y if direction == "local-y" else z
    return {"Global X": (1.0, 0.0, 0.0),
            "Global Y": (0.0, 1.0, 0.0),
            "Global Z": (0.0, 0.0, 1.0)}.get(direction, (0.0, 0.0, 1.0))
