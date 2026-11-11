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
    if sc:
        if isinstance(sc, dict) and set(sc) == {"result"}:
            return sc["result"]
        return sc
    for c in res.content:
        if getattr(c, "type", "") == "text":
            try:
                return json.loads(c.text)
            except Exception:
                return c.text
    return None


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

            r = await call("gui_status")
            check("gui not connected", r["connected"] is False)

            print()
            if FAILS:
                print("FAILURES:", FAILS)
                raise SystemExit(1)
            print(f"ALL MCP TESTS PASSED ({len(names)} tools)")


asyncio.run(main())
