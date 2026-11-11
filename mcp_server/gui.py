"""Minimal client for the OpenSees Studio GUI bridge."""

from __future__ import annotations

import itertools
import json
import socket
from typing import Any, Dict, Optional


class GuiClient:
    def __init__(self) -> None:
        self.sock: Optional[socket.socket] = None
        self.host = "127.0.0.1"
        self.port = 8765
        self.last_error = ""
        self._ids = itertools.count(1)
        self._buffer = b""

    @property
    def connected(self) -> bool:
        return self.sock is not None

    # ------------------------------------------------------------------ #
    def connect(self, host: str = "127.0.0.1", port: int = 8765,
                timeout: float = 3.0) -> Dict[str, Any]:
        self.close()
        try:
            self.sock = socket.create_connection((host, port), timeout=timeout)
            self.sock.settimeout(30.0)
            self.host, self.port = host, port
            self._buffer = b""
            return self.call("ping", timeout=timeout)
        except Exception as exc:
            self.close()
            self.last_error = f"{type(exc).__name__}: {exc}"
            raise RuntimeError(
                f"Cannot connect to OpenSees Studio on {host}:{port}. "
                "Start the app with the '--bridge' flag.") from exc

    def close(self) -> None:
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
        self.sock = None
        self._buffer = b""

    # ------------------------------------------------------------------ #
    def call(self, cmd: str, params: Optional[dict] = None,
             timeout: float = 30.0) -> Any:
        if self.sock is None:
            raise RuntimeError("Not connected to OpenSees Studio.")
        request = {"id": next(self._ids), "cmd": cmd, "params": params or {}}
        try:
            self.sock.settimeout(timeout)
            self.sock.sendall(json.dumps(request).encode("utf-8") + b"\n")
            while b"\n" not in self._buffer:
                chunk = self.sock.recv(65536)
                if not chunk:
                    raise ConnectionError("GUI closed the connection")
                self._buffer += chunk
            line, self._buffer = self._buffer.split(b"\n", 1)
            response = json.loads(line.decode("utf-8"))
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            self.close()
            raise RuntimeError(f"GUI bridge error: {exc}") from exc

        if not response.get("ok"):
            raise RuntimeError(response.get("error", "unknown GUI error"))
        return response.get("result")
