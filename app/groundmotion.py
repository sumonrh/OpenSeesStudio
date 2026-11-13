"""Ground-motion readers for time-history analysis.

The readers return acceleration values in **g**.  The solver multiplies them
by the model gravity acceleration (mm/s2) and the user scale factor before
creating the OpenSees Path time series.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

from .model import G_ACC, GroundMotionRecord, TimeHistoryCase

_NUMBER = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
_NPTS_OLD = re.compile(r"NPTS\s*=\s*(\d+).*?DT\s*=\s*([0-9.eE+\-]+)",
                       re.IGNORECASE)
_NPTS_NEW = re.compile(r"^\s*(\d+)\s+([0-9.eE+\-]+)\s+NPTS\s*,\s*DT",
                       re.IGNORECASE)


@dataclass
class GroundMotionData:
    dt: float
    values: List[float]
    source: str
    format: str
    note: str = ""

    @property
    def npts(self) -> int:
        return len(self.values)

    @property
    def duration(self) -> float:
        return max(self.dt * max(len(self.values) - 1, 0), 0.0)


def _float_tokens(line: str) -> List[float]:
    return [float(token) for token in _NUMBER.findall(line)]


def _read_text(path: str | Path) -> List[str]:
    return Path(path).read_text(encoding="utf-8", errors="ignore").splitlines()


def _find_header(lines: List[str]) -> Tuple[int, float, int] | None:
    """Return (dt, npts, data_start) for an AT2/NGA header, if present."""
    for index, line in enumerate(lines[:20]):
        old = _NPTS_OLD.search(line)
        if old:
            return float(old.group(2)), int(old.group(1)), index + 1
        new = _NPTS_NEW.match(line.strip())
        if new:
            return float(new.group(2)), int(new.group(1)), index + 1
    return None


def read_at2(path: str | Path) -> Tuple[float, List[float], str]:
    lines = _read_text(path)
    header = _find_header(lines)
    if header is None:
        raise ValueError(
            f"{path}: no 'NPTS, DT' header found - not a PEER AT2 file.")
    dt, npts, start = header
    values: List[float] = []
    for line in lines[start:]:
        values.extend(_float_tokens(line))
    if not values:
        raise ValueError(f"{path}: the AT2 header has no data after it.")
    if len(values) < npts:
        raise ValueError(
            f"{path}: header announces {npts} values but only {len(values)} "
            "are present.")
    return dt, values[:npts], f"PEER AT2, {npts} points, dt={dt:g} s"


def read_two_column(path: str | Path) -> Tuple[float, List[float], str]:
    rows: List[Tuple[float, float]] = []
    for line_no, line in enumerate(_read_text(path), start=1):
        if not line.strip():
            continue
        tokens = _float_tokens(line)
        if len(tokens) != 2:
            raise ValueError(
                f"{path}:{line_no}: expected time and acceleration, got "
                f"{len(tokens)} numeric values.")
        rows.append((tokens[0], tokens[1]))
    if len(rows) < 2:
        raise ValueError(f"{path}: fewer than two time/acceleration rows.")
    times = [row[0] for row in rows]
    steps = [times[i + 1] - times[i] for i in range(len(times) - 1)]
    dt = sum(steps) / len(steps)
    if dt <= 0.0:
        raise ValueError(f"{path}: the time column is not increasing.")
    if any(abs(step - dt) > max(1e-3 * abs(dt), 1e-9) for step in steps):
        raise ValueError(f"{path}: the time step is not uniform.")
    return dt, [row[1] for row in rows], (
        f"two-column record, {len(rows)} points, dt={dt:g} s")


def read_single_column(path: str | Path, dt: float) -> Tuple[float, List[float], str]:
    if dt <= 0.0:
        raise ValueError("A positive time step is required for a single-column record.")
    values: List[float] = []
    for line in _read_text(path):
        values.extend(_float_tokens(line))
    if not values:
        raise ValueError(f"{path}: no numeric acceleration values found.")
    return float(dt), values, (
        f"single-column record, {len(values)} points, dt={dt:g} s")


def detect_format(path: str | Path) -> str:
    lines = _read_text(path)
    if _find_header(lines) is not None:
        return "at2"
    rows = [line for line in lines if line.strip()]
    if len(rows) >= 3:
        parsed = [_float_tokens(line) for line in rows[:20]]
        if all(len(tokens) == 2 for tokens in parsed):
            times = [tokens[0] for tokens in parsed]
            if all(times[i + 1] > times[i] for i in range(len(times) - 1)):
                return "two_column"
    return "single_column"


def read_file(path: str | Path, fmt: str, dt: float) -> GroundMotionData:
    path = Path(path)
    if not path.exists():
        raise ValueError(f"Ground-motion file not found:\n{path}")
    actual = detect_format(path) if fmt in ("", "auto") else fmt
    if actual == "at2":
        step, values, note = read_at2(path)
    elif actual == "two_column":
        step, values, note = read_two_column(path)
    elif actual == "single_column":
        step, values, note = read_single_column(path, dt)
    else:
        raise ValueError(f"Unknown ground-motion format: {fmt}")
    return GroundMotionData(step, values, "file", actual,
                            f"{path.name}: {note}")


def load_ground_motion(case: TimeHistoryCase,
                       records: dict | None = None) -> GroundMotionData:
    """Return the acceleration history in g, truncated to ``case.n_steps``.

    ``source='catalog'`` resolves ``case.record`` through ``records`` (the
    project's ground-motion catalog).  The catalog record's own scale is
    applied before the case scale in the solver.
    """
    if case.source == "sine":
        if case.dt <= 0.0:
            raise ValueError("The time step must be positive.")
        if case.n_steps <= 0:
            raise ValueError("The number of steps must be positive for a sine motion.")
        if case.sine_period <= 0.0:
            raise ValueError("The sine period must be positive.")
        values = [
            case.sine_amplitude * math.sin(
                2.0 * math.pi * (index * case.dt) / case.sine_period)
            for index in range(case.n_steps)
        ]
        return GroundMotionData(
            case.dt, values, "sine", "sine",
            f"sine, amplitude={case.sine_amplitude:g} g, "
            f"period={case.sine_period:g} s, {case.n_steps} steps")

    if case.source == "catalog":
        record = (records or {}).get(int(case.record))
        if record is None:
            raise ValueError(
                f"Ground-motion catalog record {case.record} does not exist.")
        step = record.dt if record.dt > 0.0 else case.dt
        motion = read_file(record.path, record.format, step)
        if abs(record.scale - 1.0) > 1e-12:
            motion.values = [value * record.scale for value in motion.values]
        motion.source = "catalog"
        motion.note = f"{record.name}: {motion.note}"
        if case.n_steps > 0:
            motion.values = motion.values[:case.n_steps]
        if not motion.values:
            raise ValueError(f"Catalog record '{record.name}' has no values.")
        return motion

    motion = read_file(case.path, case.format, case.dt)
    if case.n_steps > 0:
        motion.values = motion.values[:case.n_steps]
    if not motion.values:
        raise ValueError("The ground-motion record contains no values.")
    return motion


def spectrum_from_record(record: GroundMotionRecord,
                         periods: list[float],
                         damping_ratio: float = 0.05) -> list[float]:
    """Compute a pseudo-acceleration spectrum (g) from a catalog record.

    A unit-mass SDOF oscillator is integrated with Newmark's average-
    acceleration method for each period.  T = 0 returns the peak ground
    acceleration.
    """
    motion = read_file(record.path, record.format,
                       record.dt if record.dt > 0.0 else 0.01)
    values = [value * record.scale * G_ACC for value in motion.values]
    if not values:
        raise ValueError(f"Catalog record '{record.name}' has no values.")
    dt = motion.dt
    ag = values
    pga = max(abs(value) for value in ag) / G_ACC
    gamma, beta = 0.5, 0.25
    result: list[float] = []
    for period in periods:
        period = float(period)
        if period <= 1e-9:
            result.append(pga)
            continue
        omega = 2.0 * math.pi / period
        stiffness = omega * omega
        damping = 2.0 * damping_ratio * omega
        u = 0.0
        v = 0.0
        a = -ag[0]
        peak = 0.0
        for acceleration in ag:
            k_eff = (stiffness + damping * gamma / (beta * dt)
                     + 1.0 / (beta * dt * dt))
            p_eff = (-acceleration
                     + u / (beta * dt * dt)
                     + v / (beta * dt)
                     + (1.0 / (2.0 * beta) - 1.0) * a
                     + damping * (gamma * u / (beta * dt)
                                  + (gamma / beta - 1.0) * v
                                  + dt * (gamma / (2.0 * beta) - 1.0) * a))
            u_new = p_eff / k_eff
            v_new = (gamma / (beta * dt) * (u_new - u)
                     + (1.0 - gamma / beta) * v
                     + dt * (1.0 - gamma / (2.0 * beta)) * a)
            a_new = (u_new - u) / (beta * dt * dt) - v / (beta * dt) \
                - (1.0 / (2.0 * beta) - 1.0) * a
            u, v, a = u_new, v_new, a_new
            peak = max(peak, abs(u))
        result.append(omega * omega * peak / G_ACC)
    return result
