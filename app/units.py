"""Display unit system for the user interface.

The model, project files, Tcl export and the MCP server always work in
kN, mm, tonne and seconds.  The unit selector converts values only at the
user-interface boundary, so changing it never alters the stored model.
"""

from __future__ import annotations

from typing import Final

FORCE_UNITS: Final = ("kN", "N", "kip", "lbs")
LENGTH_UNITS: Final = ("m", "mm", "in", "ft")

# display unit -> base unit (kN or mm)
_FORCE_TO_BASE: Final = {"kN": 1.0, "N": 0.001,
                         "kip": 4.4482216152605, "lbs": 0.0044482216152605}
_LENGTH_TO_BASE: Final = {"mm": 1.0, "m": 1000.0,
                          "in": 25.4, "ft": 304.8}


class Units:
    """Current force/length display units with conversion helpers."""

    def __init__(self) -> None:
        self.force_name = "kN"
        self.length_name = "m"
        self._fb = 1.0
        self._lb = 1000.0

    # ------------------------------------------------------------- selection
    def set(self, force: str | None = None, length: str | None = None) -> bool:
        if force in _FORCE_TO_BASE:
            self.force_name = force
            self._fb = _FORCE_TO_BASE[force]
        if length in _LENGTH_TO_BASE:
            self.length_name = length
            self._lb = _LENGTH_TO_BASE[length]
        return True

    # ---------------------------------------------------------- base -> view
    def force(self, v: float) -> float:
        return v / self._fb

    def length(self, v: float) -> float:
        return v / self._lb

    def moment(self, v: float) -> float:
        return v / (self._fb * self._lb)

    def dist(self, v: float) -> float:
        return v * self._lb / self._fb

    def stress(self, v: float) -> float:
        return v * self._lb * self._lb / self._fb

    def area(self, v: float) -> float:
        return v / (self._lb * self._lb)

    def inertia(self, v: float) -> float:
        return v / (self._lb ** 4)

    def density(self, v: float) -> float:
        return v * (self._lb ** 3)

    # ---------------------------------------------------------- view -> base
    def force_base(self, v: float) -> float:
        return v * self._fb

    def length_base(self, v: float) -> float:
        return v * self._lb

    def moment_base(self, v: float) -> float:
        return v * self._fb * self._lb

    def dist_base(self, v: float) -> float:
        return v * self._fb / self._lb

    def stress_base(self, v: float) -> float:
        return v * self._fb / (self._lb * self._lb)

    def area_base(self, v: float) -> float:
        return v * (self._lb * self._lb)

    def inertia_base(self, v: float) -> float:
        return v * (self._lb ** 4)

    def density_base(self, v: float) -> float:
        return v / (self._lb ** 3)

    # ---------------------------------------------------------------- labels
    @property
    def force_unit(self) -> str:
        return self.force_name

    @property
    def length_unit(self) -> str:
        return self.length_name

    @property
    def length_decimals(self) -> int:
        """Decimals that keep roughly 0.001 mm resolution in every length unit."""
        return {"mm": 3, "m": 6, "in": 5, "ft": 6}[self.length_name]

    @property
    def moment_unit(self) -> str:
        return f"{self.force_name}·{self.length_name}"

    @property
    def dist_unit(self) -> str:
        return f"{self.force_name}/{self.length_name}"

    @property
    def stress_unit(self) -> str:
        return f"{self.force_name}/{self.length_name}²"

    @property
    def area_unit(self) -> str:
        return f"{self.length_name}²"

    @property
    def inertia_unit(self) -> str:
        return f"{self.length_name}⁴"

    @property
    def density_unit(self) -> str:
        return f"t/{self.length_name}³"

    def label(self) -> str:
        return f"{self.force_name} · {self.length_name} · t · s"


UNITS = Units()
