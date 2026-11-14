"""Local JSON bridge that lets an MCP server drive the running GUI.

Listens on 127.0.0.1 only.  Each request is one JSON object per line:

    {"id": 1, "cmd": "ping", "params": {}}

and each response is one JSON object per line.
"""

from __future__ import annotations

import base64
import json
from typing import Any, Dict

from PySide6.QtCore import QObject
from PySide6.QtNetwork import QHostAddress, QTcpServer, QTcpSocket

from .opsgen import ModalResults, StaticResults


class GuiBridge(QObject):
    def __init__(self, window, port: int = 8765) -> None:
        super().__init__(window)
        self.window = window
        self.port = port
        self.server = QTcpServer(self)
        self.server.newConnection.connect(self._accept)
        self._buffers: Dict[QTcpSocket, bytes] = {}
        self._clients: list[QTcpSocket] = []

    # ------------------------------------------------------------------ server
    def start(self):
        ok = self.server.listen(QHostAddress.LocalHost, self.port)
        return ok, self.server.errorString()

    def stop(self) -> None:
        for sock in list(self._clients):
            sock.disconnectFromHost()
        self.server.close()

    def _accept(self) -> None:
        while self.server.hasPendingConnections():
            sock = self.server.nextPendingConnection()
            self._clients.append(sock)
            self._buffers[sock] = b""
            sock.readyRead.connect(lambda s=sock: self._read(s))
            sock.disconnected.connect(lambda s=sock: self._drop(s))

    def _drop(self, sock: QTcpSocket) -> None:
        self._buffers.pop(sock, None)
        if sock in self._clients:
            self._clients.remove(sock)
        sock.deleteLater()

    # ------------------------------------------------------------------ io
    def _read(self, sock: QTcpSocket) -> None:
        self._buffers[sock] += bytes(sock.readAll())
        while b"\n" in self._buffers[sock]:
            line, self._buffers[sock] = self._buffers[sock].split(b"\n", 1)
            if not line.strip():
                continue
            try:
                req = json.loads(line.decode("utf-8"))
            except Exception as exc:
                self._send(sock, {"id": None, "ok": False, "error": f"bad json: {exc}"})
                continue
            self._send(sock, self._dispatch(req))

    @staticmethod
    def _send(sock: QTcpSocket, payload: dict) -> None:
        sock.write(json.dumps(payload, separators=(",", ":")).encode("utf-8") + b"\n")
        sock.flush()

    # ------------------------------------------------------------------ commands
    def _dispatch(self, req: dict) -> dict:
        rid = req.get("id")
        cmd = str(req.get("cmd", ""))
        params = req.get("params") or {}
        try:
            result = self._execute(cmd, params)
            return {"id": rid, "ok": True, "result": result}
        except Exception as exc:  # noqa: BLE001 - report to the client
            return {"id": rid, "ok": False, "error": f"{type(exc).__name__}: {exc}"}

    def _execute(self, cmd: str, params: dict) -> Any:
        w = self.window
        if cmd == "ping":
            return {"name": "OpenSees Studio", "version": "1.0",
                    "nodes": len(w.project.nodes),
                    "elements": len(w.project.elements),
                    "project": w.project.title,
                    "locked": bool(w.model_locked)}
        if cmd == "get_project":
            return w.project.to_dict()
        if cmd == "load_project":
            data = params.get("project") or {}
            w.apply_project_dict(data, fit=bool(params.get("fit", True)))
            return {"nodes": len(w.project.nodes), "elements": len(w.project.elements)}
        if cmd == "fit":
            w.viewport.fit()
            return True
        if cmd == "set_scenario":
            name = str(params.get("name", ""))
            if name:
                w.scenario_combo.setCurrentText(name)
                w.viewport.load_scenario = name
                w.viewport.update()
            return w.scenario_combo.currentText()
        if cmd == "set_deformed_scale":
            try:
                scale = float(params.get("scale", 0) or 0)
            except (TypeError, ValueError):
                scale = 0.0
            w.scale_spin.setValue(scale)
            w.viewport.deformed_scale = scale if scale > 0 else None
            w.viewport.update()
            return {"scale": scale if scale > 0 else "auto"}
        if cmd == "screenshot":
            if params.get("viewport_only", True):
                pix = w.viewport.grab()
            else:
                pix = w.grab()
            from PySide6.QtCore import QBuffer, QIODevice

            buf = QBuffer()
            buf.open(QIODevice.WriteOnly)
            pix.save(buf, "PNG")
            return {"png_base64": base64.b64encode(bytes(buf.data())).decode("ascii"),
                    "width": pix.width(), "height": pix.height()}
        if cmd == "show_static":
            w.bridge_show_static(params)
            return True
        if cmd == "show_mode":
            w.bridge_show_mode(params)
            return True
        if cmd == "select":
            nodes = [int(t) for t in params.get("nodes", [])]
            elems = [int(t) for t in params.get("elements", [])]
            w.viewport.select_nodes(nodes)
            if elems:
                w.viewport.select_elements(elems, additive=True)
            return True
        if cmd == "set_visibility":
            mode = str(params.get("mode", "all")).lower()
            nodes = [int(t) for t in params.get("nodes", [])]
            elems = [int(t) for t in params.get("elements", [])]
            if mode == "all":
                w.viewport.clear_visibility()
            else:
                w.viewport.clear_selection()
                if nodes:
                    w.viewport.select_nodes(nodes)
                if elems:
                    w.viewport.select_elements(elems, additive=True)
                if mode == "activate":
                    w.activate_selection()
                elif mode == "deactivate":
                    w.deactivate_selection()
                else:
                    raise ValueError(f"unknown visibility mode '{mode}'")
            return {"hidden_nodes": len(w.viewport.hidden_nodes),
                    "hidden_elements": len(w.viewport.hidden_elements)}
        if cmd == "set_labels":
            for action, key in ((w.a_node_labels, "node_labels"),
                                (w.a_element_labels, "element_labels")):
                value = params.get(key)
                if value is not None and bool(action.isChecked()) != bool(value):
                    action.trigger()
            return {"node_labels": bool(w.viewport.show_node_labels),
                    "element_labels": bool(w.viewport.show_element_labels)}
        raise ValueError(f"unknown command '{cmd}'")


def static_payload(res: StaticResults) -> dict:
    return {"scenario": res.scenario,
            "displacements": {str(k): v for k, v in res.displacements.items()},
            "reactions": {str(k): v for k, v in res.reactions.items()},
            "element_forces": {str(k): v for k, v in res.element_forces.items()},
            "element_kind": {str(k): v for k, v in res.element_kind.items()},
            "max_disp": res.max_disp}


def modal_payload(res: ModalResults, mode: int = 1) -> dict:
    return {"mode": mode,
            "modes": [{"mode": m.mode, "eigenvalue": m.eigenvalue, "omega": m.omega,
                       "period": m.period, "frequency": m.frequency} for m in res.modes],
            "shapes": {str(k): v for k, v in res.shapes.items()}}
