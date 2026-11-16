"""Single source of truth for the OpenSees Studio version."""

from __future__ import annotations

import re

APP_VERSION = "1.0.13"
GITHUB_OWNER = "sumonrh"
GITHUB_REPO = "OpenSeesStudio"
RELEASES_API = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"


def version_tuple(value: str):
    """Numeric parts of a version tag, e.g. ``v1.0.10`` -> ``(1, 0, 10)``."""
    parts = re.findall(r"\d+", str(value or ""))
    return tuple(int(part) for part in parts) or (0,)


def is_newer(latest: str, current: str = APP_VERSION) -> bool:
    """True when *latest* is a numerically newer version than *current*."""
    a, b = version_tuple(latest), version_tuple(current)
    width = max(len(a), len(b))
    return a + (0,) * (width - len(a)) > b + (0,) * (width - len(b))
