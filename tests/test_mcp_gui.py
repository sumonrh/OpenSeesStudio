"""MCP -> running GUI bridge test (starts the app with --bridge)."""

import asyncio
import base64
import json
import os
import socket
import subprocess
import sys
import time

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8799
FAILS = []


def check(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name} {detail}")
    if not cond:
        FAILS.append(name)


def wait_port(port, timeout=40.0):
    end = time.time() + timeout
    while time.time() < end:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.3)
    return False


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
    app_exe = os.environ.get("APP_EXE", "")
    app_cmd = ([app_exe, "--bridge", str(PORT)] if app_exe
               else [sys.executable, "-m", "app.main", "--bridge", str(PORT)])
    app = subprocess.Popen(app_cmd, cwd=ROOT, env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        print("== starting GUI ==")
        check("bridge port open", wait_port(PORT), f"({PORT})")
        if FAILS:
            return

        mcp_exe = os.environ.get("MCP_EXE", "")
        if mcp_exe:
            params = StdioServerParameters(command=mcp_exe, args=[], cwd=ROOT, env=env)
        else:
            params = StdioServerParameters(command=sys.executable,
                                           args=["-m", "mcp_server"], cwd=ROOT, env=env)
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                async def call(name, args=None):
                    return payload(await session.call_tool(name, args or {}))

                r = await call("gui_connect", {"port": PORT})
                check("gui_connect", r["ok"] is True, f"({r['gui']})")

                r = await call("gui_status")
                check("gui_status connected", r["connected"] is True)

                r = await call("project_new", {"title": "Live bridge model"})
                r = await call("add_section", {"name": "Rect 300x600",
                                               "shape": "Rectangle", "b": 300, "h": 600})
                sec = r["tag"]
                r = await call("add_nodes", {"points": [[0, 0, 0], [4000, 0, 0]]})
                n1, n2 = r["nodes"]
                r = await call("add_elements", {"kind": "beam", "node_tags": [n1, n2],
                                                "material": 1, "section": sec})
                e1 = r["elements"][0]
                await call("assign_supports", {"tags": [n1]})
                await call("add_nodal_loads", {"node_tags": [n2], "case": "DL",
                                               "values": [0, 0, 10, 0, 0, 0]})

                r = await call("gui_status")
                info = r["gui"]
                check("GUI received nodes", info["nodes"] == 2, f"({info['nodes']})")
                check("GUI received elements", info["elements"] == 1,
                      f"({info['elements']})")

                r = await call("run_static", {"scenario": "DL"})
                check("analysis through MCP", abs(r["max_disp_mm"] - 0.197531) < 1e-4,
                      f"({r['max_disp_mm']:.6f} mm)")

                raw = await session.call_tool("gui_screenshot", {"viewport_only": True})
                images = [c for c in raw.content if getattr(c, "type", "") == "image"]
                check("screenshot returned image", len(images) == 1)
                if images:
                    data = images[0].data
                    blob = base64.b64decode(data)
                    out = os.path.join(os.environ.get("TEMP", "."), "mcp_gui_shot.png")
                    with open(out, "wb") as fh:
                        fh.write(blob)
                    check("screenshot png size", len(blob) > 5000,
                          f"({len(blob)} bytes -> {out})")

                r = await call("gui_show_results")
                check("gui_show_results", r["showing"] == "static", f"({r})")

                r = await call("run_modal", {"n_modes": 3})
                r = await call("gui_show_results")
                check("gui_show_results modal", r["showing"] == "modal", f"({r})")

                r = await call("gui_sync", {"fit": True})
                check("gui_sync", r["ok"] is True)

                print()
                if FAILS:
                    print("FAILURES:", FAILS)
                    raise SystemExit(1)
                print("ALL MCP GUI-BRIDGE TESTS PASSED")
    finally:
        app.terminate()
        try:
            app.wait(timeout=10)
        except subprocess.TimeoutExpired:
            app.kill()


asyncio.run(main())
