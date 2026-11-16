"""Section property calculations ported from Section Property Pro.

The geometry engine uses Green's theorem for area, centroid and second
moments.  Torsion and warping are obtained from a small plane Saint-Venant
finite-element solve on a triangular grid, with closed-form values used for
the standard parametric shapes where they are exact.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

Point = Tuple[float, float]
Polygon = List[Point]


# --------------------------------------------------------------------------- #
# Polygon properties
# --------------------------------------------------------------------------- #
def polygon_properties(points: Sequence[Point]) -> dict:
    """Area, centroid and centroidal second moments of one polygon."""
    n = len(points)
    empty = {"A": 0.0, "Cx": 0.0, "Cy": 0.0,
             "Ixc": 0.0, "Iyc": 0.0, "Ixyc": 0.0}
    if n < 3:
        return empty

    signed_a = 0.0
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        signed_a += x1 * y2 - x2 * y1
    if abs(signed_a) < 1e-12:
        return empty
    pts = list(points) if signed_a > 0 else list(reversed(points))

    a = cx = cy = ix = iy = ixy = 0.0
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        cross = x1 * y2 - x2 * y1
        a += cross
        cx += (x1 + x2) * cross
        cy += (y1 + y2) * cross
        ix += (y1 * y1 + y1 * y2 + y2 * y2) * cross
        iy += (x1 * x1 + x1 * x2 + x2 * x2) * cross
        ixy += cross * (x1 * y2 + 2.0 * x1 * y1 + 2.0 * x2 * y2 + x2 * y1)

    a /= 2.0
    if abs(a) < 1e-12:
        return empty
    cx /= 6.0 * a
    cy /= 6.0 * a
    ix /= 12.0
    iy /= 12.0
    ixy /= 24.0
    return {"A": abs(a), "Cx": cx, "Cy": cy,
            "Ixc": ix - a * cy * cy, "Iyc": iy - a * cx * cx,
            "Ixyc": ixy - a * cx * cy}


def composite_properties(outers: Sequence[Polygon], holes: Sequence[Polygon],
                         exact: Optional[dict] = None) -> Optional[dict]:
    """Combine several outer polygons and subtract holes."""
    if exact is not None:
        return dict(exact)
    out_data = [polygon_properties(p) for p in outers]
    hole_data = [polygon_properties(p) for p in holes]
    total_a = 0.0
    sum_cxa = 0.0
    sum_cya = 0.0
    for p in out_data:
        total_a += p["A"]
        sum_cxa += p["Cx"] * p["A"]
        sum_cya += p["Cy"] * p["A"]
    for p in hole_data:
        total_a -= p["A"]
        sum_cxa -= p["Cx"] * p["A"]
        sum_cya -= p["Cy"] * p["A"]
    if total_a < 1e-12:
        return None

    cx = sum_cxa / total_a
    cy = sum_cya / total_a
    gix = giy = gixy = 0.0
    for p in out_data:
        gix += p["Ixc"] + p["A"] * (p["Cy"] - cy) ** 2
        giy += p["Iyc"] + p["A"] * (p["Cx"] - cx) ** 2
        gixy += p["Ixyc"] + p["A"] * (p["Cx"] - cx) * (p["Cy"] - cy)
    for p in hole_data:
        gix -= p["Ixc"] + p["A"] * (p["Cy"] - cy) ** 2
        giy -= p["Iyc"] + p["A"] * (p["Cx"] - cx) ** 2
        gixy -= p["Ixyc"] + p["A"] * (p["Cx"] - cx) * (p["Cy"] - cy)

    y_top = y_bot = x_right = x_left = 0.0
    for poly in outers:
        for x, y in poly:
            y_top = max(y_top, y - cy)
            y_bot = max(y_bot, cy - y)
            x_right = max(x_right, x - cx)
            x_left = max(x_left, cx - x)

    avg = (gix + giy) / 2.0
    diff = (gix - giy) / 2.0
    radius = math.hypot(diff, gixy)
    theta = 0.0
    if abs(diff) > 1e-12 or abs(gixy) > 1e-12:
        theta = math.atan2(-gixy, diff) / 2.0
    alpha = math.degrees(theta)
    while alpha >= 90.0:
        alpha -= 180.0
    while alpha < -90.0:
        alpha += 180.0

    def safe(value: float) -> float:
        return max(0.0, value)

    return {
        "A": total_a, "Cx": cx, "Cy": cy,
        "Ix": gix, "Iy": giy, "Ixy": gixy,
        "Ip": gix + giy,
        "I1": avg + radius, "I2": avg - radius, "alpha": alpha,
        "SxTop": gix / y_top if y_top > 0 else 0.0,
        "SxBot": gix / y_bot if y_bot > 0 else 0.0,
        "SyRight": giy / x_right if x_right > 0 else 0.0,
        "SyLeft": giy / x_left if x_left > 0 else 0.0,
        "rx": math.sqrt(safe(gix / total_a)),
        "ry": math.sqrt(safe(giy / total_a)),
    }


# --------------------------------------------------------------------------- #
# Finite-element Saint-Venant torsion and warping
# --------------------------------------------------------------------------- #
def _point_in_polygon(x: float, y: float, poly: Sequence[Point]) -> bool:
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def _point_on_boundary(x: float, y: float, poly: Sequence[Point],
                       eps: float = 1e-7) -> bool:
    n = len(poly)
    for i in range(n):
        ax, ay = poly[i]
        bx, by = poly[(i + 1) % n]
        cross = (y - ay) * (bx - ax) - (x - ax) * (by - ay)
        if abs(cross) > eps * max(1.0, math.hypot(bx - ax, by - ay)):
            continue
        dot = (x - ax) * (bx - ax) + (y - ay) * (by - ay)
        length = (bx - ax) ** 2 + (by - ay) ** 2
        if -eps <= dot <= length + eps:
            return True
    return False


def _inside_section(x: float, y: float, outers: Sequence[Polygon],
                    holes: Sequence[Polygon]) -> bool:
    if not any(_point_in_polygon(x, y, p) or _point_on_boundary(x, y, p)
               for p in outers):
        return False
    return not any(_point_in_polygon(x, y, p) or _point_on_boundary(x, y, p)
                   for p in holes)


def fem_torsion(outers: Sequence[Polygon], holes: Sequence[Polygon],
                cx: float, cy: float, area: float, ix: float, iy: float,
                ixy: float, max_nodes: int = 9000) -> dict:
    """Solve the Saint-Venant torsion problem with linear triangles.

    Returns ``J``, ``Cw`` and solver diagnostics.  A matrix-free
    preconditioner-free conjugate-gradient solve keeps the calculation inside
    the application's NumPy dependency.
    """
    shifted_outers = [[(x - cx, y - cy) for x, y in p] for p in outers]
    shifted_holes = [[(x - cx, y - cy) for x, y in p] for p in holes]
    xs = [x for p in shifted_outers for x, _ in p]
    ys = [y for p in shifted_outers for _, y in p]
    if not xs or not ys:
        return {"J": 0.0, "Cw": None, "converged": False,
                "warnings": ["No section boundary."]}
    min_x, max_x, min_y, max_y = min(xs), max(xs), min(ys), max(ys)
    span_x, span_y = max_x - min_x, max_y - min_y
    max_span = max(span_x, span_y, 0.001)
    min_span = max(min(span_x, span_y), 0.001)
    resolution = max(60, math.ceil(max_span / (min_span / 12.0)))
    resolution = min(resolution, 180)
    h = max_span / resolution
    cols = math.ceil(span_x / h) + 2
    rows = math.ceil(span_y / h) + 2
    while cols * rows > max_nodes * 2 and resolution > 30:
        resolution = int(resolution * 0.8)
        h = max_span / resolution
        cols = math.ceil(span_x / h) + 2
        rows = math.ceil(span_y / h) + 2
    start_x = min_x - h
    start_y = min_y - h

    active: Dict[Tuple[int, int], int] = {}
    node_xy: List[Tuple[float, float]] = []

    def node_id(row: int, col: int) -> int:
        key = (row, col)
        idx = active.get(key)
        if idx is None:
            idx = len(node_xy)
            active[key] = idx
            node_xy.append((start_x + col * h, start_y + row * h))
        return idx

    triangles: List[Tuple[int, int, int]] = []
    for r in range(rows - 1):
        for c in range(cols - 1):
            px = start_x + (c + 0.5) * h
            py = start_y + (r + 0.5) * h
            if not _inside_section(px, py, shifted_outers, shifted_holes):
                continue
            i00 = node_id(r, c)
            i10 = node_id(r, c + 1)
            i01 = node_id(r + 1, c)
            i11 = node_id(r + 1, c + 1)
            triangles.append((i00, i10, i11))
            triangles.append((i00, i11, i01))

    if len(node_xy) < 3 or not triangles:
        return {"J": 0.0, "Cw": None, "converged": False,
                "warnings": ["Mesh generation failed."]}

    nodes = np.asarray(node_xy, dtype=float)
    elems = np.asarray(triangles, dtype=np.int64)
    x1 = nodes[elems[:, 0], 0]
    y1 = nodes[elems[:, 0], 1]
    x2 = nodes[elems[:, 1], 0]
    y2 = nodes[elems[:, 1], 1]
    x3 = nodes[elems[:, 2], 0]
    y3 = nodes[elems[:, 2], 1]
    ae = 0.5 * np.abs((x2 - x1) * (y3 - y1) - (x3 - x1) * (y2 - y1))
    valid = ae > 1e-12
    if not np.any(valid):
        return {"J": 0.0, "Cw": None, "converged": False,
                "warnings": ["Degenerate mesh."]}
    elems = elems[valid]
    x1, y1, x2, y2, x3, y3, ae = (a[valid] for a in
                                  (x1, y1, x2, y2, x3, y3, ae))

    b1 = y2 - y3
    b2 = y3 - y1
    b3 = y1 - y2
    c1 = x3 - x2
    c2 = x1 - x3
    c3 = x2 - x1
    btb = np.empty((len(elems), 3, 3), dtype=float)
    b = np.stack((b1, b2, b3), axis=1)
    c = np.stack((c1, c2, c3), axis=1)
    btb = b[:, :, None] * b[:, None, :] + c[:, :, None] * c[:, None, :]
    coeff = 1.0 / (4.0 * ae)
    cx_e = (x1 + x2 + x3) / 3.0
    cy_e = (y1 + y2 + y3) / 3.0
    fe = 0.5 * (np.stack((b1, b2, b3), axis=1) * cy_e[:, None]
                - np.stack((c1, c2, c3), axis=1) * cx_e[:, None])
    force = np.bincount(elems.ravel(), weights=fe.ravel(),
                        minlength=len(nodes))

    # Union-find for connected components; one node per component is pinned.
    parent = list(range(len(nodes)))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for a, b, cidx in elems:
        union(int(a), int(b))
        union(int(a), int(cidx))
    comps: Dict[int, List[int]] = {}
    for i in range(len(nodes)):
        comps.setdefault(find(i), []).append(i)
    pinned = np.array([members[0] for members in comps.values()], dtype=np.int64)
    warnings: List[str] = []
    if len(comps) > 1:
        warnings.append(f"{len(comps)} disconnected regions; warping constant "
                        "is only meaningful for a connected section.")

    row = elems
    p0 = np.asarray(force, dtype=float)
    p0[pinned] = 0.0

    def matvec(vec: np.ndarray) -> np.ndarray:
        pe = vec[elems]
        local = coeff[:, None, None] * btb * pe[:, None, :]
        contrib = local.sum(axis=2)
        out = np.bincount(row.ravel(), weights=contrib.ravel(),
                          minlength=len(nodes))
        out[pinned] = 0.0
        return out

    diag = np.bincount(elems.ravel(),
                       weights=(coeff[:, None]
                                * np.diagonal(btb, axis1=1, axis2=2)).ravel(),
                       minlength=len(nodes))
    diag = np.where(diag > 1e-30, diag, 1.0)
    diag[pinned] = 1.0

    r = p0.copy()
    r[pinned] = 0.0
    z = r / diag
    p = z.copy()
    rzold = float(r @ z)
    target = 1e-9 * max(1.0, float(np.linalg.norm(p0)))
    converged = math.sqrt(float(r @ r)) < target
    w = np.zeros(len(nodes), dtype=float)
    iterations = 0
    if not converged and rzold > 0:
        max_iter = 6000
        for iterations in range(1, max_iter + 1):
            ap = matvec(p)
            pap = float(p @ ap)
            if pap <= 1e-30:
                break
            alpha = rzold / pap
            w += alpha * p
            r -= alpha * ap
            r[pinned] = 0.0
            if math.sqrt(float(r @ r)) < target:
                converged = True
                break
            z = r / diag
            rznew = float(r @ z)
            if rznew <= 0:
                break
            p = z + (rznew / rzold) * p
            p[pinned] = 0.0
            rzold = rznew
    if not converged:
        warnings.append("Torsion solver did not fully converge; J is approximate.")

    we = w[elems]
    wkw = float(np.sum(coeff * np.einsum("mi,mij,mj->m", we, btb, we)))
    ixx = (ae / 6.0) * (y1 * y1 + y2 * y2 + y3 * y3 + y1 * y2 + y2 * y3 + y3 * y1)
    iyy = (ae / 6.0) * (x1 * x1 + x2 * x2 + x3 * x3 + x1 * x2 + x2 * x3 + x3 * x1)
    mesh_ip = float(np.sum(ixx + iyy))
    sum_x = x1 + x2 + x3
    sum_y = y1 + y2 + y3
    sum_w = we.sum(axis=1)
    q_w = float(np.sum(ae * sum_w / 3.0))
    i_w = float(np.sum((ae / 6.0) * (we[:, 0] ** 2 + we[:, 1] ** 2
                                     + we[:, 2] ** 2 + we[:, 0] * we[:, 1]
                                     + we[:, 1] * we[:, 2] + we[:, 2] * we[:, 0])))
    i_xw = float(np.sum((ae / 12.0) * (sum_x * sum_w
                                       + x1 * we[:, 0] + x2 * we[:, 1]
                                       + x3 * we[:, 2])))
    i_yw = float(np.sum((ae / 12.0) * (sum_y * sum_w
                                       + y1 * we[:, 0] + y2 * we[:, 1]
                                       + y3 * we[:, 2])))
    torsion_j = max(0.0, mesh_ip - wkw)

    warping = None
    if len(comps) == 1 and converged and area > 0:
        det = ix * iy - ixy * ixy
        xs = ys = 0.0
        if abs(det) > 1e-12:
            xs = (ixy * i_xw - iy * i_yw) / det
            ys = (ix * i_xw - ixy * i_yw) / det
        warping = i_w - (q_w * q_w / area) - ys * i_xw + xs * i_yw
        if warping < -1e-10:
            warnings.append("Computed Cw is negative; the mesh may be too coarse.")
        warping = max(0.0, warping)

    return {"J": torsion_j, "Cw": warping, "converged": converged,
            "iterations": iterations, "nodes": len(nodes),
            "elements": len(elems), "components": len(comps),
            "warnings": warnings}


# --------------------------------------------------------------------------- #
# Parametric shape generators
# --------------------------------------------------------------------------- #
def circle_points(radius: float, n: int = 72) -> Polygon:
    return [(radius * math.cos(2.0 * math.pi * i / n),
             radius * math.sin(2.0 * math.pi * i / n)) for i in range(n)]


def regular_polygon_points(diameter: float, n: int) -> Polygon:
    radius = diameter / 2.0
    start = math.pi / n
    return [(radius * math.cos(start + 2.0 * math.pi * i / n),
             radius * math.sin(start + 2.0 * math.pi * i / n))
            for i in range(n)]


SHAPE_DEFS = {
    "IShape": ("I-Section", ("b", "d", "tf", "tw")),
    "TShape": ("T-Section", ("b", "d", "tf", "tw")),
    "CShape": ("C-Channel", ("b", "d", "tf", "tw")),
    "LShape": ("L-Angle", ("b", "d", "t")),
    "Rectangle": ("Solid Rectangle", ("b", "d")),
    "RectHollow": ("Rectangular Hollow", ("b", "d", "b_inner", "d_inner")),
    "OpenBox": ("Open Top Box", ("b", "d", "tf", "tw")),
    "SolidCircle": ("Solid Circle", ("d",)),
    "Pipe": ("Pipe", ("d", "t")),
    "Hexagon": ("Solid Hexagon", ("d",)),
    "Octagon": ("Solid Octagon", ("d",)),
    "DoubleAngle": ("Double Angle", ("b", "d", "t", "gap")),
    "DoubleChannel": ("Double Channel", ("b", "d", "tf", "tw", "gap")),
    "OctagonHole": ("Octagon with Hole", ("b", "d", "c", "holeR")),
}

PARAM_LABELS = {
    "b": "Width b", "d": "Depth d", "tf": "Flange / wall tf",
    "tw": "Web tw", "t": "Thickness t", "b_inner": "Inner width",
    "d_inner": "Inner depth", "gap": "Gap", "c": "Chamfer c",
    "holeR": "Hole radius", "BDiameter": "Diameter b",
}


def _shape_geometry(shape: str, p: dict) -> dict:
    b = float(p.get("b", 0.0))
    d = float(p.get("d", 0.0))
    tf = float(p.get("tf", 0.0))
    tw = float(p.get("tw", 0.0))
    t = float(p.get("t", 0.0))

    def positive(*values: float) -> None:
        for value in values:
            if value <= 0:
                raise ValueError("All dimensions must be positive.")

    if shape == "Rectangle":
        positive(b, d)
        return {"outers": [[(-b / 2, d / 2), (b / 2, d / 2),
                            (b / 2, -d / 2), (-b / 2, -d / 2)]],
                "holes": [], "J": None, "Cw": None}
    if shape == "IShape":
        positive(b, d, tf, tw)
        if 2 * tf >= d:
            raise ValueError("Flange thickness exceeds total depth.")
        if tw >= b:
            raise ValueError("Web thickness exceeds total width.")
        iy = (2 * tf * b ** 3 + max(0.0, d - 2 * tf) * tw ** 3) / 12.0
        return {
            "outers": [[(-b / 2, d / 2), (b / 2, d / 2),
                        (b / 2, d / 2 - tf), (tw / 2, d / 2 - tf),
                        (tw / 2, -d / 2 + tf), (b / 2, -d / 2 + tf),
                        (b / 2, -d / 2), (-b / 2, -d / 2),
                        (-b / 2, -d / 2 + tf), (-tw / 2, -d / 2 + tf),
                        (-tw / 2, d / 2 - tf), (-b / 2, d / 2 - tf)]],
            "holes": [],
            "J": (2.0 / 3.0) * b * tf ** 3
                 + (1.0 / 3.0) * max(0.0, d - 2 * tf) * tw ** 3,
            "Cw": iy * (d - tf) ** 2 / 4.0}
    if shape == "TShape":
        positive(b, d, tf, tw)
        if tf >= d:
            raise ValueError("Flange thickness exceeds total depth.")
        if tw >= b:
            raise ValueError("Web thickness exceeds total width.")
        return {
            "outers": [[(-b / 2, d / 2), (b / 2, d / 2),
                        (b / 2, d / 2 - tf), (tw / 2, d / 2 - tf),
                        (tw / 2, -d / 2), (-tw / 2, -d / 2),
                        (-tw / 2, d / 2 - tf), (-b / 2, d / 2 - tf)]],
            "holes": [],
            "J": (1.0 / 3.0) * b * tf ** 3
                 + (1.0 / 3.0) * max(0.0, d - tf) * tw ** 3,
            "Cw": None}
    if shape == "CShape":
        positive(b, d, tf, tw)
        if 2 * tf >= d:
            raise ValueError("Flange thickness exceeds total depth.")
        if tw >= b:
            raise ValueError("Web thickness exceeds total width.")
        return {
            "outers": [[(-b / 2, d / 2), (b / 2, d / 2),
                        (b / 2, d / 2 - tf), (-b / 2 + tw, d / 2 - tf),
                        (-b / 2 + tw, -d / 2 + tf), (b / 2, -d / 2 + tf),
                        (b / 2, -d / 2), (-b / 2, -d / 2)]],
            "holes": [],
            "J": (2.0 / 3.0) * b * tf ** 3
                 + (1.0 / 3.0) * max(0.0, d - 2 * tf) * tw ** 3,
            "Cw": None}
    if shape == "LShape":
        positive(b, d, t)
        if t >= d or t >= b:
            raise ValueError("Thickness exceeds leg length.")
        return {
            "outers": [[(-b / 2, d / 2), (-b / 2 + t, d / 2),
                        (-b / 2 + t, -d / 2 + t), (b / 2, -d / 2 + t),
                        (b / 2, -d / 2), (-b / 2, -d / 2)]],
            "holes": [],
            "J": (1.0 / 3.0) * b * t ** 3
                 + (1.0 / 3.0) * max(0.0, d - t) * t ** 3,
            "Cw": None}
    if shape == "RectHollow":
        bi = float(p.get("b_inner", 0.0))
        di = float(p.get("d_inner", 0.0))
        positive(b, d, bi, di)
        if bi >= b or di >= d:
            raise ValueError("Inner dimensions must be smaller than the outer.")
        tw_avg = (b - bi) / 2.0
        tf_avg = (d - di) / 2.0
        am = (b - tw_avg) * (d - tf_avg)
        integral = 2.0 * (d - tf_avg) / tw_avg + 2.0 * (b - tw_avg) / tf_avg
        return {
            "outers": [[(-b / 2, d / 2), (b / 2, d / 2),
                        (b / 2, -d / 2), (-b / 2, -d / 2)]],
            "holes": [[(-bi / 2, di / 2), (bi / 2, di / 2),
                       (bi / 2, -di / 2), (-bi / 2, -di / 2)]],
            "J": 4.0 * am * am / integral, "Cw": 0.0}
    if shape == "OpenBox":
        positive(b, d, tf, tw)
        if tf >= d:
            raise ValueError("Bottom flange exceeds total depth.")
        if 2 * tw >= b:
            raise ValueError("Webs exceed total width.")
        return {
            "outers": [[(-b / 2, d / 2), (-b / 2 + tw, d / 2),
                        (-b / 2 + tw, -d / 2 + tf), (b / 2 - tw, -d / 2 + tf),
                        (b / 2 - tw, d / 2), (b / 2, d / 2),
                        (b / 2, -d / 2), (-b / 2, -d / 2)]],
            "holes": [],
            "J": (1.0 / 3.0) * b * tf ** 3
                 + (2.0 / 3.0) * max(0.0, d - tf) * tw ** 3,
            "Cw": None}
    if shape == "SolidCircle":
        positive(d)
        r = d / 2.0
        inertia = math.pi * r ** 4 / 4.0
        return {"outers": [circle_points(r)], "holes": [],
                "J": 2.0 * inertia, "Cw": 0.0,
                "exact": {"A": math.pi * r * r, "Cx": 0.0, "Cy": 0.0,
                          "Ix": inertia, "Iy": inertia, "Ixy": 0.0,
                          "Ip": 2.0 * inertia,
                          "I1": inertia, "I2": inertia, "alpha": 0.0,
                          "SxTop": inertia / r, "SxBot": inertia / r,
                          "SyRight": inertia / r, "SyLeft": inertia / r,
                          "rx": r / 2.0, "ry": r / 2.0}}
    if shape == "Pipe":
        positive(d, t)
        if t >= d / 2.0:
            raise ValueError("Wall thickness must be less than the radius.")
        ro, ri = d / 2.0, d / 2.0 - t
        area = math.pi * (ro * ro - ri * ri)
        inertia = math.pi * (ro ** 4 - ri ** 4) / 4.0
        return {"outers": [circle_points(ro)], "holes": [circle_points(ri)],
                "J": 2.0 * inertia, "Cw": 0.0,
                "exact": {"A": area, "Cx": 0.0, "Cy": 0.0,
                          "Ix": inertia, "Iy": inertia, "Ixy": 0.0,
                          "Ip": 2.0 * inertia,
                          "I1": inertia, "I2": inertia, "alpha": 0.0,
                          "SxTop": inertia / ro, "SxBot": inertia / ro,
                          "SyRight": inertia / ro, "SyLeft": inertia / ro,
                          "rx": math.sqrt(max(0.0, inertia / area)),
                          "ry": math.sqrt(max(0.0, inertia / area))}}
    if shape in ("Hexagon", "Octagon"):
        positive(d)
        n = 6 if shape == "Hexagon" else 8
        return {"outers": [regular_polygon_points(d, n)], "holes": [],
                "J": None, "Cw": None}
    if shape == "DoubleAngle":
        gap = float(p.get("gap", 0.0))
        positive(b, d, t)
        if t >= d or t >= b:
            raise ValueError("Thickness exceeds leg length.")
        return {
            "outers": [
                [(-gap / 2, d / 2), (-gap / 2 - t, d / 2),
                 (-gap / 2 - t, -d / 2 + t), (-gap / 2 - b, -d / 2 + t),
                 (-gap / 2 - b, -d / 2), (-gap / 2, -d / 2)],
                [(gap / 2, d / 2), (gap / 2, -d / 2),
                 (gap / 2 + b, -d / 2), (gap / 2 + b, -d / 2 + t),
                 (gap / 2 + t, -d / 2 + t), (gap / 2 + t, d / 2)]],
            "holes": [],
            "J": 2.0 * ((1.0 / 3.0) * b * t ** 3
                        + (1.0 / 3.0) * max(0.0, d - t) * t ** 3),
            "Cw": None}
    if shape == "DoubleChannel":
        gap = float(p.get("gap", 0.0))
        positive(b, d, tf, tw)
        if 2 * tf >= d:
            raise ValueError("Flange thickness exceeds total depth.")
        if tw >= b:
            raise ValueError("Web thickness exceeds total width.")
        return {
            "outers": [
                [(-gap / 2, d / 2), (-gap / 2 - b, d / 2),
                 (-gap / 2 - b, d / 2 - tf), (-gap / 2 - tw, d / 2 - tf),
                 (-gap / 2 - tw, -d / 2 + tf), (-gap / 2 - b, -d / 2 + tf),
                 (-gap / 2 - b, -d / 2), (-gap / 2, -d / 2)],
                [(gap / 2, d / 2), (gap / 2, -d / 2),
                 (gap / 2 + b, -d / 2), (gap / 2 + b, -d / 2 + tf),
                 (gap / 2 + tw, -d / 2 + tf), (gap / 2 + tw, d / 2 - tf),
                 (gap / 2 + b, d / 2 - tf), (gap / 2 + b, d / 2)]],
            "holes": [],
            "J": 2.0 * ((2.0 / 3.0) * b * tf ** 3
                        + (1.0 / 3.0) * max(0.0, d - 2 * tf) * tw ** 3),
            "Cw": None}
    if shape == "OctagonHole":
        c = float(p.get("c", 0.0))
        hole_r = float(p.get("holeR", 0.0))
        positive(b, d)
        if c >= b / 2 or c >= d / 2:
            raise ValueError("Chamfer too large for the dimensions.")
        if hole_r >= b / 2 or hole_r >= d / 2:
            raise ValueError("Hole exceeds the boundary.")
        outers = [[(-b / 2 + c, d / 2), (b / 2 - c, d / 2),
                   (b / 2, d / 2 - c), (b / 2, -d / 2 + c),
                   (b / 2 - c, -d / 2), (-b / 2 + c, -d / 2),
                   (-b / 2, -d / 2 + c), (-b / 2, d / 2 - c)]]
        holes = [circle_points(hole_r)] if hole_r > 0 else []
        return {"outers": outers, "holes": holes, "J": None, "Cw": None}
    raise ValueError(f"Unknown section shape {shape}.")


# --------------------------------------------------------------------------- #
# Public result
# --------------------------------------------------------------------------- #
@dataclass
class SectionPropertyResult:
    shape: str
    params: dict
    outers: List[Polygon]
    holes: List[Polygon]
    A: float = 0.0
    Cx: float = 0.0
    Cy: float = 0.0
    Ix: float = 0.0
    Iy: float = 0.0
    Ixy: float = 0.0
    Ip: float = 0.0
    I1: float = 0.0
    I2: float = 0.0
    alpha: float = 0.0
    SxTop: float = 0.0
    SxBot: float = 0.0
    SyRight: float = 0.0
    SyLeft: float = 0.0
    rx: float = 0.0
    ry: float = 0.0
    J: float = 0.0
    Cw: Optional[float] = None
    torsion_source: str = ""
    warping_source: str = ""
    mesh_nodes: int = 0
    mesh_elements: int = 0
    warnings: List[str] = field(default_factory=list)

    @property
    def mass_per_length(self) -> float:
        """Steel mass in kg/m using rho = 7850 kg/m3."""
        return self.A * 1e-6 * 7850.0

    def outline(self) -> Tuple[List[Point], Optional[List[Point]]]:
        """Single outer/inner pair for preview, or empty for multi-part shapes."""
        if len(self.outers) != 1:
            return [], None
        outer = [(x - self.Cx, y - self.Cy) for x, y in self.outers[0]]
        inner = None
        if len(self.holes) == 1:
            inner = [(x - self.Cx, y - self.Cy) for x, y in self.holes[0]]
        return outer, inner


def compute_section_properties(shape: str, params: dict,
                               use_fem: bool = True,
                               max_nodes: int = 9000) -> SectionPropertyResult:
    geometry = _shape_geometry(shape, params)
    outers = geometry["outers"]
    holes = geometry["holes"]
    exact = geometry.get("exact")
    props = composite_properties(outers, holes, exact)
    if props is None:
        raise ValueError("The section has no positive area.")

    result = SectionPropertyResult(
        shape=shape, params={k: float(v) for k, v in params.items()},
        outers=outers, holes=holes,
        A=props["A"], Cx=props["Cx"], Cy=props["Cy"],
        Ix=props["Ix"], Iy=props["Iy"], Ixy=props["Ixy"],
        Ip=props["Ip"], I1=props["I1"], I2=props["I2"],
        alpha=props["alpha"], SxTop=props["SxTop"], SxBot=props["SxBot"],
        SyRight=props["SyRight"], SyLeft=props["SyLeft"],
        rx=props["rx"], ry=props["ry"])

    exact_j = geometry.get("J")
    exact_cw = geometry.get("Cw")
    if exact_j is not None:
        result.J = float(exact_j)
        result.torsion_source = "closed form"
    if exact_cw is not None:
        result.Cw = float(exact_cw)
        result.warping_source = "closed form"

    if use_fem and (exact_j is None or exact_cw is None):
        fem = fem_torsion(outers, holes, props["Cx"], props["Cy"],
                          props["A"], props["Ix"], props["Iy"], props["Ixy"],
                          max_nodes=max_nodes)
        if exact_j is None:
            result.J = float(fem["J"] or 0.0)
            result.torsion_source = "FEM"
        if exact_cw is None:
            result.Cw = fem["Cw"]
            result.warping_source = "FEM" if fem["Cw"] is not None else "not available"
        result.mesh_nodes = int(fem.get("nodes", 0))
        result.mesh_elements = int(fem.get("elements", 0))
        result.warnings.extend(fem.get("warnings", []))
    elif result.Cw is None:
        result.warping_source = "not available"
    return result
