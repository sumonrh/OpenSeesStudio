"""Built-in demonstration model: a three-storey 3D steel frame."""

from __future__ import annotations

from .model import (Element, ElementLoad, LoadCase, LoadCombination,
                    NodalLoad, Node, Project, Section, default_project)


def demo_frame() -> Project:
    p = default_project()
    p.title = "3-Storey Steel Frame"

    col = Section(4, "H 400x400x12x20", "I-Shape", b=400, h=400, tw=12, tf=20)
    col.compute()
    p.sections[col.tag] = col

    xs = [0.0, 6000.0, 12000.0]
    ys = [0.0, 6000.0]
    zs = [0.0, 3500.0, 7000.0, 10500.0]

    tags = {}

    def add_node(x, y, z) -> int:
        key = (x, y, z)
        if key in tags:
            return tags[key]
        t = p.next_node()
        p.nodes[t] = Node(t, x, y, z)
        tags[key] = t
        return t

    # columns
    for x in xs:
        for y in ys:
            for k in range(len(zs) - 1):
                i = add_node(x, y, zs[k])
                j = add_node(x, y, zs[k + 1])
                t = p.next_element()
                p.elements[t] = Element(t, "beam", [i, j], 1, col.tag, [1.0, 0.0, 0.0])

    # beams in X
    for z in zs[1:]:
        for y in ys:
            for a, b in zip(xs, xs[1:]):
                i = add_node(a, y, z)
                j = add_node(b, y, z)
                t = p.next_element()
                p.elements[t] = Element(t, "beam", [i, j], 1, 2, [0.0, 0.0, 1.0])

    # beams in Y
    for z in zs[1:]:
        for x in xs:
            i = add_node(x, ys[0], z)
            j = add_node(x, ys[1], z)
            t = p.next_element()
            p.elements[t] = Element(t, "beam", [i, j], 1, 2, [0.0, 0.0, 1.0])

    # supports
    for x in xs:
        for y in ys:
            p.nodes[tags[(x, y, 0.0)]].support = [True] * 6

    # load cases
    p.cases = {}
    p.cases["DL"] = LoadCase("DL", "Dead")
    p.cases["LL"] = LoadCase("LL", "Live")
    p.cases["WIND"] = LoadCase("WIND", "Wind")
    p.self_weight = {"DL": 1.0}

    # distributed loads on the horizontal beams of every floor
    uid = 1
    for t, e in list(p.elements.items()):
        p0 = p.node_xyz(e.nodes[0])
        p1 = p.node_xyz(e.nodes[1])
        if abs(p1[2] - p0[2]) > 1.0:          # skip columns
            continue
        if p0[2] <= 0.01:
            continue
        p.elem_loads.append(ElementLoad(uid, t, "DL", "uniform", "Global Z",
                                        -15.0 / 1000.0))
        uid += 1
        p.elem_loads.append(ElementLoad(uid, t, "LL", "uniform", "Global Z",
                                        -10.0 / 1000.0))
        uid += 1

    # wind: nodal forces at each floor, total per floor 30/45/60 kN
    nid = 1
    for k, z in enumerate(zs[1:], start=1):
        total = 15.0 * k * len(xs) * len(ys)
        for x in xs:
            for y in ys:
                p.nodal_loads.append(NodalLoad(nid, tags[(x, y, z)], "WIND",
                                               [total / (len(xs) * len(ys)), 0, 0, 0, 0, 0]))
                nid += 1

    p.combos = {}
    p.combos["1.4DL+1.6LL"] = LoadCombination("1.4DL+1.6LL",
                                             [("DL", 1.4), ("LL", 1.6)])
    p.combos["1.2DL+1.0WIND"] = LoadCombination("1.2DL+1.0WIND",
                                                [("DL", 1.2), ("WIND", 1.0)])
    p.settings["last_case"] = "1.4DL+1.6LL"
    return p
