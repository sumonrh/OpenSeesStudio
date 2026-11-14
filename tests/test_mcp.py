"""End-to-end MCP protocol test over stdio (headless mode)."""

import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAILS = []


def check(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name} {detail}")
    if not cond:
        FAILS.append(name)


def payload(res):
    sc = getattr(res, "structuredContent", None)
    if sc is None:
        sc = getattr(res, "structured_content", None)
    if sc:
        if isinstance(sc, dict) and set(sc) == {"result"}:
            return sc["result"]
        return sc
    items = []
    for c in res.content:
        if getattr(c, "type", "") == "text":
            try:
                items.append(json.loads(c.text))
            except Exception:
                items.append(c.text)
    if len(items) == 1:
        return items[0]
    return items


async def main():
    env = {**os.environ, "PYTHONPATH": ROOT}
    exe = os.environ.get("MCP_EXE", "")
    if exe:
        params = StdioServerParameters(command=exe, args=[], cwd=ROOT, env=env)
        print(f"using MCP executable: {exe}")
    else:
        params = StdioServerParameters(command=sys.executable,
                                       args=["-m", "mcp_server"],
                                       cwd=ROOT, env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            names = {t.name for t in tools.tools}
            print("== tools ==")
            check("tool count >= 30", len(names) >= 30, f"({len(names)})")
            for required in ("add_nodes", "add_elements", "copy_nodes", "mirror_nodes",
                             "assign_supports", "add_nodal_loads", "add_element_loads",
                             "add_load_case", "add_load_combination", "run_static",
                             "run_modal", "get_static_results", "gui_connect"):
                check(f"tool {required}", required in names)

            resources = await session.list_resources()
            uris = {str(r.uri) for r in resources.resources}
            check("project resource", "opensees://project" in uris, f"({uris})")

            async def call(name, args=None):
                return payload(await session.call_tool(name, args or {}))

            print("== build a cantilever through MCP ==")
            r = await call("project_new", {"title": "MCP cantilever"})
            check("project_new", r["title"] == "MCP cantilever")

            r = await call("add_section", {"name": "Rect 300x600", "shape": "Rectangle",
                                           "b": 300, "h": 600})
            sec = r["tag"]
            check("add_section", abs(r["Iy"] - 5.4e9) < 1.0)

            r = await call("add_nodes", {"points": [[0, 0, 0], [4000, 0, 0]]})
            n1, n2 = r["nodes"]
            check("add_nodes", r["nodes"] == [1, 2])

            r = await call("add_elements", {"kind": "beam", "node_tags": [n1, n2],
                                            "material": 1, "section": sec})
            e1 = r["elements"][0]
            check("add_elements", r["elements"] == [1])

            r = await call("assign_supports", {"tags": [n1], "dof": "fixed"})
            check("assign_supports", r["dof"] == [1] * 6)

            r = await call("add_load_case", {"name": "WIND", "kind": "Wind"})
            check("add_load_case", "WIND" in r["cases"])

            r = await call("add_nodal_loads", {"node_tags": [n2], "case": "DL",
                                               "values": [0, 0, 10, 0, 0, 0]})
            check("add_nodal_loads", r["nodes"] == [n2])

            r = await call("check_model")
            check("check_model ok", r["ok"] is True, f"({r['errors']})")

            print("== analysis ==")
            r = await call("run_static", {"scenario": "DL"})
            check("run_static max disp", abs(r["max_disp_mm"] - 0.197531) < 1e-4,
                  f"({r['max_disp_mm']:.6f} mm)")

            r = await call("get_static_results", {"node_tags": [n2]})
            disp = r["displacements"][str(n2)]
            check("get_static_results uz", abs(disp[2] - 0.197531) < 1e-4,
                  f"(uz={disp[2]:.6f})")

            r = await call("get_static_results", {"element_tags": [e1],
                                                  "include_forces": True})
            forces = r["element_forces"][str(e1)]
            check("element force My", abs(abs(forces[4]) - 40000) < 1,
                  f"(My={forces[4]:.1f})")

            r = await call("add_load_combination",
                           {"name": "1.4DL", "factors": {"DL": 1.4}})
            check("add_load_combination", "1.4DL" in r["combinations"])
            r = await call("run_static", {"scenario": "1.4DL"})
            check("combination run", abs(r["max_disp_mm"] - 1.4 * 0.197531) < 1e-4,
                  f"({r['max_disp_mm']:.6f} mm)")

            r = await call("run_modal", {"n_modes": 3})
            check("run_modal", len(r["modes"]) == 3 and r["modes"][0]["period"] > 0,
                  f"(T1={r['modes'][0]['period']:.5f} s)")
            r = await call("get_mode_shape", {"mode": 1})
            check("get_mode_shape", str(n2) in r)

            print("== replication ==")
            r = await call("copy_nodes", {"tags": [n1, n2], "delta": [0, 6000, 0],
                                          "count": 1})
            check("copy_nodes", len(r["nodes"]) == 2 and len(r["elements"]) == 1,
                  f"({len(r['nodes'])} nodes, {len(r['elements'])} elements)")
            r = await call("mirror_nodes", {"tags": [n1, n2], "plane": "YZ",
                                            "copy": True})
            check("mirror_nodes", len(r["nodes"]) == 2, f"({len(r['nodes'])})")
            r = await call("move_nodes", {"tags": [n1], "delta": [0, 0, -500]})
            check("move_nodes", r["delta"] == [0.0, 0.0, -500.0])

            print("== project io ==")
            tmp = os.path.join(os.environ.get("TEMP", "."), "mcp_project.ospj")
            r = await call("project_save", {"path": tmp})
            check("project_save", os.path.exists(tmp), f"({r['path']})")
            r = await call("project_open", {"path": tmp})
            check("project_open", r["nodes"] == 6, f"({r['nodes']} nodes)")

            tcl = os.path.join(os.environ.get("TEMP", "."), "mcp_model.tcl")
            r = await call("export_tcl", {"path": tcl})
            text = open(tcl, encoding="utf-8").read()
            check("export_tcl", "elasticBeamColumn" in text, f"({r['lines']} lines)")

            print("== wizards, hinges and dynamics ==")
            r = await call("generate_frame_2d", {"bays_x": 2, "storeys": 2,
                                                 "replace": True})
            check("generate_frame_2d", r["nodes"] == 9 and r["elements"] == 10,
                  f"({r['nodes']} nodes, {r['elements']} elements)")
            r = await call("generate_frame_3d", {"bays_x": 2, "bays_y": 1,
                                                 "storeys": 1})
            check("generate_frame_3d", r["nodes"] == 12 and r["elements"] == 13,
                  f"({r['nodes']} nodes, {r['elements']} elements)")
            r = await call("generate_truss_2d", {"panels": 4})
            check("generate_truss_2d", r["nodes"] == 10 and r["elements"] == 17,
                  f"({r['nodes']} nodes, {r['elements']} elements)")
            r = await call("generate_truss_3d", {"panels": 3})
            check("generate_truss_3d", r["nodes"] == 16 and r["elements"] == 46,
                  f"({r['nodes']} nodes, {r['elements']} elements)")
            r = await call("generate_bridge", {"spans": 2, "girders": 3,
                                               "span_length": 20000,
                                               "cross_spacing": 5000})
            check("generate_bridge", r["nodes"] == 27 and r["elements"] == 42,
                  f"({r['nodes']} nodes, {r['elements']} elements)")

            r = await call("generate_frame_2d", {"bays_x": 2, "storeys": 2,
                                                 "replace": True})
            materials = await call("list_hinge_materials")
            check("list_hinge_materials", len(materials) >= 10)
            r = await call("add_hinge_definition",
                           {"name": "Steel hinge", "material": "Steel01",
                            "params": {"fy": 0.235}})
            hinge = r["tag"]
            check("add_hinge_definition", r["material"] == "Steel01")
            r = await call("assign_hinges", {"element_tags": [1, 2], "hinge": hinge})
            check("assign_hinges", r["elements"] == [1, 2])
            r = await call("list_hinge_assignments")
            check("list_hinge_assignments", len(r) == 2)
            r = await call("update_hinge_definition",
                           {"tag": hinge, "name": "H1", "length_ratio": 0.15})
            check("update_hinge_definition", r["length_ratio"] == 0.15)

            await call("add_load_case", {"name": "LAT", "kind": "Wind"})
            nodes = await call("list_nodes")
            top = max(nodes, key=lambda n: n["z"])["tag"]
            await call("add_nodal_loads", {"node_tags": [top], "case": "LAT",
                                           "values": [10, 0, 0, 0, 0, 0]})
            r = await call("run_pushover",
                           {"gravity_case": "DL", "lateral_case": "LAT",
                            "control_node": top, "target_displacement": 20,
                            "steps": 3})
            check("run_pushover", r["steps"] == 3 and r["points"] >= 4,
                  f"({r['points']} points)")
            r = await call("get_pushover_results", {"include_steps": True})
            check("get_pushover_results", len(r["steps"]) >= 3,
                  f"({len(r['steps'])} points)")
            r = await call("get_pushover_step", {"step": -1})
            check("get_pushover_step", "node_displacements" in r)
            check("delete_hinge_definition",
                  (await call("delete_hinge_definition", {"tag": hinge}))["ok"])

            r = await call("configure_time_history",
                           {"source": "sine", "dt": 0.01, "n_steps": 20,
                            "sine_amplitude": 0.1, "sine_period": 1.0})
            check("configure_time_history", r["n_steps"] == 20)
            r = await call("run_time_history")
            check("run_time_history", r["steps"] == 20, f"({r['steps']} steps)")
            r = await call("get_time_history_results", {"step": 5})
            check("get_time_history_results", r["step"] == 5)

            r = await call("configure_response_spectrum",
                           {"periods": [0.0, 0.2, 0.5], 
                            "accelerations": [0.4, 0.8, 0.5],
                            "n_modes": 3})
            check("configure_response_spectrum", r["n_modes"] == 3)
            r = await call("run_response_spectrum")
            check("run_response_spectrum", r["modes"] >= 1,
                  f"({r['modes']} modes)")
            r = await call("get_response_spectrum_results", {"include_forces": True})
            check("get_response_spectrum_results", r["peak_disp"] > 0)

            gm_path = os.path.join(os.environ.get("TEMP", "."), "mcp_motion.txt")
            with open(gm_path, "w", encoding="utf-8") as fh:
                for i in range(40):
                    fh.write(f"{i * 0.01:.2f} {0.05 * (1 if i % 2 else -1):.4f}\n")
            r = await call("add_ground_motion", {"path": gm_path,
                                                 "name": "Test motion"})
            gm = r["tag"]
            check("add_ground_motion", r["npts"] == 40 and r["dt"] > 0)
            r = await call("record_response_spectrum",
                           {"tag": gm, "periods": [0.0, 0.2, 0.5]})
            check("record_response_spectrum", len(r["accelerations"]) == 3)
            check("delete_ground_motion",
                  (await call("delete_ground_motion", {"tag": gm}))["ok"])

            r = await call("import_tcl", {"path": tcl})
            check("import_tcl", r["nodes"] == 6, f"({r['nodes']} nodes)")

            r = await call("gui_status")
            check("gui not connected", r["connected"] is False)

            print()
            if FAILS:
                print("FAILURES:", FAILS)
                raise SystemExit(1)
            print(f"ALL MCP TESTS PASSED ({len(names)} tools)")


asyncio.run(main())
