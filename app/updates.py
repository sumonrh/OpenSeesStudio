"""GitHub release update check used by the ribbon update badge."""

from __future__ import annotations

import json
import os
import sys

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from .version import APP_VERSION, RELEASES_API, is_newer


def update_check_disabled() -> bool:
    """Keep the network silent in tests, offscreen sessions and frozen self-tests."""
    if os.environ.get("OPENSEES_STUDIO_NO_UPDATE_CHECK", "").lower() in (
            "1", "true", "yes", "on"):
        return True
    if os.environ.get("OPENSEES_STUDIO_IN_PROCESS") == "1":
        return True
    if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
        return True
    if "pytest" in sys.modules:
        return True
    return "--selftest" in sys.argv


class UpdateChecker(QObject):
    """Poll the latest stable GitHub release once and report a newer installer."""

    available = Signal(str, str)       # version, download/release URL
    checked = Signal(bool)             # an update is available

    def __init__(self, current: str = APP_VERSION, parent=None) -> None:
        super().__init__(parent)
        self.current = current
        self._manager: QNetworkAccessManager | None = None

    def check(self) -> None:
        if update_check_disabled():
            self.checked.emit(False)
            return
        if self._manager is None:
            self._manager = QNetworkAccessManager(self)
        request = QNetworkRequest(QUrl(RELEASES_API))
        request.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader,
                          f"OpenSeesStudio/{self.current}")
        request.setRawHeader(b"Accept", b"application/vnd.github+json")
        request.setRawHeader(b"X-GitHub-Api-Version", b"2022-11-28")
        try:
            request.setTransferTimeout(10000)
        except AttributeError:       # older Qt
            pass
        reply = self._manager.get(request)
        reply.finished.connect(lambda r=reply: self._finished(r))

    def _finished(self, reply: QNetworkReply) -> None:
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                self.checked.emit(False)
                return
            payload = json.loads(bytes(reply.readAll()).decode("utf-8", "replace"))
            if payload.get("draft") or payload.get("prerelease"):
                self.checked.emit(False)
                return
            tag = str(payload.get("tag_name") or payload.get("name") or "")
            assets = payload.get("assets") or []
            setup = next((a for a in assets
                          if "setup" in str(a.get("name", "")).lower()
                          and str(a.get("name", "")).lower().endswith((".exe", ".msi"))),
                         None)
            if setup is None:
                self.checked.emit(False)
                return
            if not is_newer(tag, self.current):
                self.checked.emit(False)
                return
            url = (setup.get("browser_download_url")
                   or payload.get("html_url") or "")
            if not url:
                self.checked.emit(False)
                return
            version = str(tag).lstrip("vV") or str(tag)
            self.available.emit(version, str(url))
            self.checked.emit(True)
        except Exception:
            self.checked.emit(False)
        finally:
            reply.deleteLater()
