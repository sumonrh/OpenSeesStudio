"""MCP test: launch the installed GUI from the server, then drive it."""

import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8802
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
    else:
        params = StdioServerParameters(command=sys.executable, args=["-m", "mcp_server"],
                                       cwd=ROOT, env=env)

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            async def call(name, args=None):
                return payload(await session.call_tool(name, args or {}))

            print("== launching the GUI from MCP ==")
            r = await call("gui_launch", {"port": PORT, "timeout": 40})
            check("gui_launch", r["ok"] is True, f"({r.get('exe')})")
            check("gui info", r["gui"]["name"] == "OpenSees Studio")

            r = await call("gui_status")
            check("gui_status", r["connected"] is True)

            r = await call("project_new", {"title": "Launched by MCP"})
            r = await call("add_nodes", {"points": [[0, 0, 0], [3000, 0, 0], [6000, 0, 0]]})
            nodes = r["nodes"]
            await call("add_elements", {"kind": "beam", "node_tags": nodes,
                                        "material": 1, "section": 1})
            await call("assign_supports", {"tags": [nodes[0]]})
            await call("add_nodal_loads", {"node_tags": [nodes[2]], "case": "DL",
                                           "values": [0, -10, 0, 0, 0, 0]})
            r = await call("gui_status")
            check("live node count", r["gui"]["nodes"] == 3, f"({r['gui']['nodes']})")
            check("live element count", r["gui"]["elements"] == 2, f"({r['gui']['elements']})")

            raw = await session.call_tool("gui_screenshot", {"viewport_only": True})
            imgs = [c for c in raw.content if getattr(c, "type", "") == "image"]
            check("screenshot", len(imgs) == 1)
            if imgs:
                import base64
                out = os.path.join(os.environ.get("TEMP", "."), "mcp_launch_shot.png")
                blob = base64.b64decode(imgs[0].data)
                with open(out, "wb") as fh:
                    fh.write(blob)
                check("screenshot size", len(blob) > 5000, f"({len(blob)} bytes)")

            print()
            if FAILS:
                print("FAILURES:", FAILS)
                raise SystemExit(1)
            print("ALL MCP GUI-LAUNCH TESTS PASSED")


asyncio.run(main())
