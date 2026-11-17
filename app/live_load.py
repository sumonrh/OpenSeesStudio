"""Bridge live-load analysis: moving truck, lane UDL and envelopes.

The engine follows the influence-line approach used by the Live Load Analyzer
for Bridges: a continuous Euler-Bernoulli beam is factorized once, four unit
point-load solves per element give the cubic influence coefficients, truck
axles are moved over the bridge in both orientations, and lane UDL envelopes
are assembled from the positive/negative parts of the influence functions.

Units are the conventional bridge units used by the source application:
span lengths in m, E in Pa, I in m4, axle loads and reactions in kN, moments in
kN m, deflections in m.  The GUI converts model section/material values.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

DEFAULT_SPANS = (20.0, 25.0, 20.0)
DEFAULT_E = 200.0e9          # Pa
DEFAULT_I = 0.005            # m4
DEFAULT_ELEMS_PER_SPAN = 20
DEFAULT_TRUCK_INCREMENT = 0.25
DEFAULT_LANE_UDL = 9.0       # kN/m
MAX_SPANS = 12
MAX_AXLES = 20
MAX_ELEMENTS = 600
MAX_SWEEP_STEPS = 6000
MIN_SWEEP_STEP = 0.02
LANE_TRUCK_FACTOR = 0.8
DLA_FACTOR = 0.25
UDL_SAMPLES = 64

CL_AXLES: Tuple[Tuple[float, float], ...] = (
    (50.0, 3.6), (125.0, 1.2), (125.0, 6.6), (175.0, 6.6), (150.0, 0.0),
)
BCL_AXLES: Tuple[Tuple[float, float], ...] = (
    (50.0, 3.6), (140.0, 1.2), (140.0, 6.6), (175.0, 6.6), (120.0, 0.0),
)
BCL_SUBDIVISIONS = (0.5, 1.0, 2.0)


@dataclass
class Span:
    length: float


@dataclass
class Axle:
    load: float
    spacing: float = 0.0


@dataclass
class LiveLoadConfig:
    E: float = DEFAULT_E
    I: float = DEFAULT_I
    elems_per_span: int = DEFAULT_ELEMS_PER_SPAN
    truck_increment: float = DEFAULT_TRUCK_INCREMENT
    load_case: str = "truck"       # truck | lane | envelope
    dla_override: Optional[float] = None
    dla_multiplier: float = 1.0
    lane_udl: float = DEFAULT_LANE_UDL
    truck_model: str = "Custom"
    bcl_subdivision: float = 1.0
    lane_name: str = "Lane 1"
    lane_start: Optional[float] = None   # m, start of lane travel
    lane_end: Optional[float] = None     # m, end of lane travel
    lane_offset: float = 0.0             # m, lateral shift (informational)


@dataclass
class EnvelopePoint:
    x: float
    max: float
    min: float


@dataclass
class ReactionEnvelope:
    x: float
    max: float
    min: float
    governing_position: float = 0.0
    governing_spacing: Optional[float] = None


@dataclass
class CaseResults:
    shear: List[EnvelopePoint] = field(default_factory=list)
    moment: List[EnvelopePoint] = field(default_factory=list)
    deflection: List[EnvelopePoint] = field(default_factory=list)
    reactions: List[ReactionEnvelope] = field(default_factory=list)
    reaction_diagrams: List[List[EnvelopePoint]] = field(default_factory=list)
    dla_used: float = 0.0
    dla_auto: bool = True
    dla_base: float = 0.0
    dla_multiplier: float = 1.0


@dataclass
class LiveLoadResults:
    load_case: str
    cases: Dict[str, CaseResults]
    spans: List[Span]
    axles: List[Axle]
    config: LiveLoadConfig
    x_nodes: List[float]
    support_positions: List[float]
    truck_positions: List[float]
    increment_used: float
    base_increment: float
    increment_reason: str
    bcl_spacings: List[float]
    influence: Dict[str, List[Tuple[float, float]]] = field(default_factory=dict)
    log: str = ""

    @property
    def selected(self) -> CaseResults:
        return self.cases[self.load_case]

    @property
    def shear(self) -> List[EnvelopePoint]:
        return self.selected.shear

    @property
    def moment(self) -> List[EnvelopePoint]:
        return self.selected.moment

    @property
    def deflection(self) -> List[EnvelopePoint]:
        return self.selected.deflection

    @property
    def reactions(self) -> List[ReactionEnvelope]:
        return self.selected.reactions

    @property
    def reaction_diagrams(self) -> List[List[EnvelopePoint]]:
        return self.selected.reaction_diagrams

    @property
    def dla_used(self) -> float:
        return self.selected.dla_used

    def summary(self) -> str:
        selected = self.selected
        if selected.dla_auto:
            dla_text = ("Auto selected-axle DLA (40/30/25%) "
                        f"x d={self.config.dla_multiplier:g}")
        elif self.load_case == "lane":
            dla_text = "No DLA on the lane case"
        else:
            dla_text = f"DLA {selected.dla_used * 100:.2f}%"
        lines = [
            f"Load case: {self.load_case}",
            f"Spans: {', '.join(f'{s.length:g}' for s in self.spans)} m",
            f"Truck: {self.config.truck_model}  ({len(self.axles)} axles)",
            ("Lane: " + self.config.lane_name
             + (f"  x={self.config.lane_start:g}..{self.config.lane_end:g} m"
                if self.config.lane_start is not None
                and self.config.lane_end is not None else "")
             + f"  lateral shift {self.config.lane_offset:g} m"),
            f"Effective sweep: {self.increment_used:.4g} m ({self.increment_reason})",
            dla_text,
            f"Positions: {len(self.truck_positions)}",
        ]
        if self.bcl_spacings:
            lines.append("BCL axle 3-4 spacings: "
                         + ", ".join(f"{v:g}" for v in self.bcl_spacings) + " m")
        if self.log:
            lines.extend(self.log.splitlines())
        return "\n".join(lines)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def preset_axles(model: str) -> List[Axle]:
    rows = BCL_AXLES if model == "BCL-625" else CL_AXLES
    return [Axle(float(load), float(spacing)) for load, spacing in rows]


def reverse_axles(axles: Sequence[Axle]) -> List[Axle]:
    return [Axle(axles[len(axles) - 1 - i].load,
                 axles[len(axles) - 2 - i].spacing if i < len(axles) - 1 else 0.0)
            for i in range(len(axles))]


def build_bcl_spacings(subdivision: float) -> List[float]:
    if subdivision not in BCL_SUBDIVISIONS:
        raise ValueError("BCL spacing subdivision must be 0.5, 1 or 2 m.")
    values = [round(6.6 + i * subdivision, 3)
              for i in range(int(11.4 / subdivision) + 1)]
    return values + [18.0]


def truck_group_dla(count: int, front_three: bool) -> float:
    if count <= 0:
        return 0.0
    if count == 1:
        return 0.40
    if count == 2:
        return 0.30
    if count == 3:
        return 0.30 if front_three else DLA_FACTOR
    return DLA_FACTOR


def resolve_dla(config: LiveLoadConfig) -> Tuple[bool, float, float]:
    multiplier = float(config.dla_multiplier)
    if not math.isfinite(multiplier):
        multiplier = 1.0
    multiplier = max(0.0, min(1.0, multiplier))
    is_auto = config.dla_override is None
    base = 0.0 if is_auto else max(0.0, float(config.dla_override))
    return is_auto, base, base * multiplier


def _max_axles_on_length(length: float, axles: Sequence[Axle]) -> int:
    best = 1
    for first in range(len(axles)):
        distance = 0.0
        count = 1
        for nxt in range(first, len(axles) - 1):
            distance += axles[nxt].spacing
            if distance > length + 1e-6:
                break
            count += 1
        best = max(best, count)
    return best


def auto_dla_info(spans: Sequence[Span], axles: Sequence[Axle]) -> Tuple[float, str]:
    best = 0.25
    count = 3
    governing = spans[0].length if spans else 0.0
    for span in spans:
        n = _max_axles_on_length(span.length, axles)
        candidate = 0.40 if n <= 1 else 0.30 if n == 2 else 0.25
        if candidate > best:
            best, count, governing = candidate, n, span.length
    text = ("1 axle on a span" if count <= 1 else
            "2 axles on a span (tandem)" if count == 2 else
            "3 or more axles on a span")
    return best, f"Auto DLA {best * 100:g}%: {text}; governing span {governing:g} m"


def compute_effective_increment(spans: Sequence[Span], axles: Sequence[Axle],
                                base: float, elems_per_span: int
                                ) -> Tuple[float, str]:
    if (not math.isfinite(base) or base <= 0 or elems_per_span < 2
            or not spans or any(s.length <= 0 for s in spans)):
        return base, "base setting"
    min_span = min(s.length for s in spans)
    gaps = [a.spacing for a in axles[:-1]
            if math.isfinite(a.spacing) and a.spacing > 0]
    truck_length = sum(a.spacing for a in axles[:-1])
    sweep_length = sum(s.length for s in spans) + 2 * truck_length
    effective = base
    reason = "base setting"
    for candidate, label in ((min_span / 40.0, "short-span control"),
                             (min_span / elems_per_span, "element control"),
                             (min(gaps) / 8.0 if gaps else math.inf,
                              "axle-spacing control")):
        if candidate < effective:
            effective, reason = candidate, label
    if effective < MIN_SWEEP_STEP:
        effective, reason = MIN_SWEEP_STEP, "minimum 0.02 m step"
    if sweep_length / effective > MAX_SWEEP_STEPS:
        effective = sweep_length / MAX_SWEEP_STEPS
        reason = "6,000 interval step cap"
    effective = math.ceil(effective * 200.0 - 1e-10) / 200.0
    return effective, reason


def validate(spans: Sequence[Span], axles: Sequence[Axle],
             config: LiveLoadConfig) -> None:
    if not spans:
        raise ValueError("At least one span is required.")
    if len(spans) > MAX_SPANS:
        raise ValueError(f"At most {MAX_SPANS} spans are supported.")
    for i, span in enumerate(spans, 1):
        if not math.isfinite(span.length) or span.length <= 0:
            raise ValueError(f"Span {i} length must be greater than zero.")
    if not math.isfinite(config.E) or config.E <= 0:
        raise ValueError("Elastic modulus E must be greater than zero.")
    if not math.isfinite(config.I) or config.I <= 0:
        raise ValueError("Moment of inertia I must be greater than zero.")
    if int(config.elems_per_span) < 2:
        raise ValueError("Elements per span must be at least 2.")
    if len(spans) * int(config.elems_per_span) > MAX_ELEMENTS:
        raise ValueError(f"The model is limited to {MAX_ELEMENTS} beam elements.")
    if not math.isfinite(config.truck_increment) or config.truck_increment <= 0:
        raise ValueError("Truck increment must be greater than zero.")
    if config.load_case not in ("truck", "lane", "envelope"):
        raise ValueError("Choose Truck, Lane or Envelope.")
    if not 1 <= len(axles) <= MAX_AXLES:
        raise ValueError(f"Enter between 1 and {MAX_AXLES} axles.")
    for i, axle in enumerate(axles, 1):
        if not math.isfinite(axle.load) or axle.load < 0:
            raise ValueError(f"Axle {i} load must be non-negative.")
        if i < len(axles) and (not math.isfinite(axle.spacing)
                               or axle.spacing < 0):
            raise ValueError(f"Axle {i} spacing must be non-negative.")
    if config.dla_override is not None and (
            not math.isfinite(config.dla_override) or config.dla_override < 0):
        raise ValueError("DLA must be non-negative.")
    if not 0.0 <= config.dla_multiplier <= 1.0:
        raise ValueError("DLA multiplier d must be between 0 and 1.")
    if not math.isfinite(config.lane_udl) or config.lane_udl < 0:
        raise ValueError("Lane UDL must be non-negative.")
    if not math.isfinite(config.lane_offset):
        raise ValueError("Lane lateral shift must be finite.")
    if (config.lane_start is not None or config.lane_end is not None):
        if config.lane_start is None or config.lane_end is None:
            raise ValueError("Provide both lane start and lane end.")
        if not (math.isfinite(config.lane_start)
                and math.isfinite(config.lane_end)):
            raise ValueError("Lane start/end must be finite.")
        if config.lane_end <= config.lane_start:
            raise ValueError("Lane end must be greater than lane start.")


def truck_positions(supports: Sequence[float], axles: Sequence[Axle],
                    step: float, lane_start: Optional[float] = None,
                    lane_end: Optional[float] = None) -> List[float]:
    """Truck lead-axle positions for the lane or the full bridge.

    The vehicle is allowed to enter and leave the lane, so the lead axle
    sweeps from ``lane_start - truck_length`` to ``lane_end + truck_length``.
    This matches the reference Live-Load-Analyzer sweep when the lane covers
    the full bridge (lane_start=0, lane_end=total span).
    """
    length = sum(a.spacing for a in axles[:-1])
    first = supports[0] if lane_start is None else float(lane_start)
    last = supports[-1] if lane_end is None else float(lane_end)
    if last <= first:
        raise ValueError("Lane end must be greater than lane start.")
    start = first - length
    end = last + length
    count = max(2, int(math.floor((end - start) / step + 1e-6)) + 1)
    values = {min(end, start + i * step) for i in range(count)}
    values.add(end)
    # Support, lane-end and axle alignment positions improve extrema.
    for edge in (list(supports) + [first, last]):
        for direction in (list(axles), reverse_axles(axles)):
            distance = 0.0
            for i, axle in enumerate(direction):
                for sign in (1, -1):
                    lead = edge + sign * distance
                    for offset in (-1e-6, 0.0, 1e-6):
                        value = lead + offset
                        if start <= value <= end:
                            values.add(value)
                if i < len(direction) - 1:
                    distance += axle.spacing
    return sorted(values)


def _fit_cubic(y0: np.ndarray, y1: np.ndarray, y2: np.ndarray,
               y3: np.ndarray) -> np.ndarray:
    d1 = y1 - y0
    d2 = y2 - 2.0 * y1 + y0
    d3 = y3 - 3.0 * y2 + 3.0 * y1 - y0
    return np.stack((
        y0 - 0.5 * d1 + 0.375 * d2 - 0.3125 * d3,
        4.0 * d1 - 4.0 * d2 + 23.0 * d3 / 6.0,
        8.0 * d2 - 12.0 * d3,
        32.0 * d3 / 3.0,
    ), axis=-1)


def _influence(coeff: np.ndarray, xi: float) -> np.ndarray:
    return ((coeff[..., 3] * xi + coeff[..., 2]) * xi + coeff[..., 1]) * xi + coeff[..., 0]


# --------------------------------------------------------------------------- #
# beam system
# --------------------------------------------------------------------------- #
class BeamSystem:
    def __init__(self, spans: Sequence[Span], config: LiveLoadConfig) -> None:
        self.spans = list(spans)
        self.config = config
        self.n_per_span = int(config.elems_per_span)
        self.n_elems = len(self.spans) * self.n_per_span
        self.n_nodes = self.n_elems + 1
        self.n_dof = self.n_nodes * 2
        self.moment_offset = 2 * self.n_elems
        self.deflection_offset = self.moment_offset + self.n_nodes
        self.reaction_offset = self.deflection_offset + self.n_nodes
        self.support_nodes = [i * self.n_per_span
                              for i in range(len(self.spans) + 1)]
        self.support_dofs = [2 * n for n in self.support_nodes]
        self.n_supports = len(self.support_nodes)
        self.n_responses = self.reaction_offset + self.n_supports
        self.x_nodes = np.zeros(self.n_nodes)
        self.lengths = np.zeros(self.n_elems)
        self.local_k = np.zeros((self.n_elems, 4, 4))
        self.K = np.zeros((self.n_dof, self.n_dof))
        self.x_shear: List[float] = []

        node = 0
        for span in self.spans:
            le = float(span.length) / self.n_per_span
            for _ in range(self.n_per_span):
                x0 = self.x_nodes[node]
                x1 = x0 + le
                self.lengths[node] = le
                self.x_shear.extend((x0, x1))
                coeff = float(config.E) * float(config.I) / le ** 3
                le2 = le * le
                matrix = np.array([
                    [12.0, 6.0 * le, -12.0, 6.0 * le],
                    [6.0 * le, 4.0 * le2, -6.0 * le, 2.0 * le2],
                    [-12.0, -6.0 * le, 12.0, -6.0 * le],
                    [6.0 * le, 2.0 * le2, -6.0 * le, 4.0 * le2],
                ]) * coeff
                self.local_k[node] = matrix
                dofs = np.arange(2 * node, 2 * node + 4)
                self.K[np.ix_(dofs, dofs)] += matrix
                self.x_nodes[node + 1] = x1
                node += 1
        self.free = np.array([i for i in range(self.n_dof)
                              if i not in set(self.support_dofs)], dtype=int)
        self.Kff = self.K[np.ix_(self.free, self.free)]
        self.supports = [float(self.x_nodes[n]) for n in self.support_nodes]
        self.coeffs = self._influence_cache()

    def _point_load_vector(self, element: int, xi: float,
                           magnitude: float) -> np.ndarray:
        le = self.lengths[element]
        x2 = xi * xi
        x3 = x2 * xi
        shapes = np.array([1.0 - 3.0 * x2 + 2.0 * x3,
                           le * (xi - 2.0 * x2 + x3),
                           3.0 * x2 - 2.0 * x3,
                           le * (-x2 + x3)])
        return -magnitude * shapes * 1000.0

    def _influence_cache(self) -> np.ndarray:
        n_cols = 4 * self.n_elems
        loads = np.zeros((self.n_dof, n_cols))
        elem_loads = np.zeros((self.n_elems, 4, n_cols))
        xs = (0.125, 0.375, 0.625, 0.875)
        for e in range(self.n_elems):
            for p, xi in enumerate(xs):
                col = 4 * e + p
                values = self._point_load_vector(e, xi, 1.0)
                dofs = np.arange(2 * e, 2 * e + 4)
                loads[dofs, col] += values
                elem_loads[e, :, col] += values
        displacement = np.zeros((self.n_dof, n_cols))
        displacement[self.free, :] = np.linalg.solve(self.Kff, loads[self.free, :])

        # End forces for every element and unit-load column.
        u_nodes = displacement.reshape(self.n_nodes, 2, n_cols)
        u_elem = np.concatenate((u_nodes[:-1], u_nodes[1:]), axis=1)
        end_forces = np.einsum("eij,ejc->eic", self.local_k, u_elem) - elem_loads

        responses = np.zeros((self.n_responses, n_cols))
        reactions = (self.K @ displacement - loads)[self.support_dofs, :] / 1000.0
        for col in range(n_cols):
            responses[0:2 * self.n_elems:2, col] = end_forces[:, 0, col] / 1000.0
            responses[1:2 * self.n_elems:2, col] = -end_forces[:, 2, col] / 1000.0
            moments = np.empty(self.n_nodes)
            moments[0] = end_forces[0, 1, col]
            moments[-1] = -end_forces[-1, 3, col]
            if self.n_nodes > 2:
                moments[1:-1] = (end_forces[1:, 1, col]
                                 - end_forces[:-1, 3, col]) / 2.0
            responses[self.moment_offset:self.moment_offset + self.n_nodes, col] = -moments / 1000.0
            responses[self.deflection_offset:self.deflection_offset + self.n_nodes, col] = displacement[0::2, col]
            responses[self.reaction_offset:, col] = reactions[:, col]

        coeffs = np.zeros((self.n_elems, self.n_responses, 4))
        for e in range(self.n_elems):
            block = responses[:, 4 * e:4 * e + 4]
            coeffs[e] = _fit_cubic(block[:, 0], block[:, 1],
                                   block[:, 2], block[:, 3])
        return coeffs

    # ------------------------------------------------------------------ loads
    def _axle_locations(self, lead: float, axles: Sequence[Axle]):
        positions = []
        distance = 0.0
        for i, axle in enumerate(axles):
            positions.append(lead - distance)
            if i < len(axles) - 1:
                distance += axle.spacing
        elements = []
        xis = []
        for pos in positions:
            if pos < -1e-9 or pos > self.x_nodes[-1] + 1e-9:
                elements.append(-1)
                xis.append(0.0)
                continue
            e = int(np.searchsorted(self.x_nodes, pos, side="right") - 1)
            e = max(0, min(self.n_elems - 1, e))
            le = self.lengths[e]
            xi = 0.0 if le <= 0 else (pos - self.x_nodes[e]) / le
            elements.append(e)
            xis.append(float(max(0.0, min(1.0, xi))))
        return elements, xis

    def response_at(self, lead: float, response: int,
                    weights: Sequence[float], axles: Sequence[Axle],
                    config: LiveLoadConfig, case: str
                    ) -> Tuple[float, float]:
        """Return (max, min) for one response at a truck lead position."""
        elements, xis = self._axle_locations(lead, axles)
        values = np.empty(len(axles))
        for i, (e, xi) in enumerate(zip(elements, xis)):
            if e < 0:
                values[i] = 0.0
            else:
                values[i] = float(_influence(self.coeffs[e, response], xi))
        w = np.asarray(weights, dtype=float)
        contrib = values * w
        if case == "lane":
            total = float(np.sum(contrib)) * LANE_TRUCK_FACTOR
            return total, total
        is_auto, base, effective = resolve_dla(config)
        if not is_auto:
            total = float(np.sum(contrib)) * (1.0 + effective)
            return total, total
        pos = values > 1e-12
        neg = values < -1e-12
        total = float(np.sum(contrib))
        pos_sum = float(np.sum(contrib[pos]))
        neg_sum = float(np.sum(contrib[neg]))
        count_pos = int(np.count_nonzero(pos))
        count_neg = int(np.count_nonzero(neg))
        front_pos = len(axles) >= 3 and bool(np.all(pos[:3]))
        front_neg = len(axles) >= 3 and bool(np.all(neg[:3]))
        mult = (max(0.0, min(1.0, float(config.dla_multiplier)))
                if is_auto else effective)
        max_value = total + truck_group_dla(count_pos, front_pos) * mult * pos_sum
        min_value = total + truck_group_dla(count_neg, front_neg) * mult * neg_sum
        return max_value, min_value

    # ----------------------------------------------------------- envelopes
    def udl_envelopes(self, w: float) -> Tuple[np.ndarray, np.ndarray]:
        maximum = np.zeros(self.n_responses)
        minimum = np.zeros(self.n_responses)
        if w <= 0:
            return maximum, minimum
        xis = (np.arange(UDL_SAMPLES) + 0.5) / UDL_SAMPLES
        for e in range(self.n_elems):
            c = self.coeffs[e]
            values = (((c[:, 3, None] * xis + c[:, 2, None]) * xis
                       + c[:, 1, None]) * xis + c[:, 0, None])
            weight = w * self.lengths[e] / UDL_SAMPLES
            maximum += np.sum(np.maximum(values, 0.0), axis=1) * weight
            minimum += np.sum(np.minimum(values, 0.0), axis=1) * weight
        return maximum, minimum

    def influence_line(self, response: int, samples_per_element: int = 16
                       ) -> List[Tuple[float, float]]:
        points: List[Tuple[float, float]] = []
        xis = np.linspace(0.0, 1.0, samples_per_element + 1)
        for e in range(self.n_elems):
            c = self.coeffs[e, response]
            values = (((c[3] * xis + c[2]) * xis + c[1]) * xis + c[0])
            for xi, value in zip(xis, values):
                points.append((float(self.x_nodes[e] + self.lengths[e] * xi),
                               float(value)))
        return points


# --------------------------------------------------------------------------- #
# analysis
# --------------------------------------------------------------------------- #
Progress = Optional[Callable[[float, str], None]]


def _combine_cases(truck: CaseResults, lane: CaseResults) -> CaseResults:
    def combine(a: List[EnvelopePoint], b: List[EnvelopePoint]) -> List[EnvelopePoint]:
        return [EnvelopePoint(pa.x, max(pa.max, pb.max), min(pa.min, pb.min))
                for pa, pb in zip(a, b)]

    reactions = []
    for a, b in zip(truck.reactions, lane.reactions):
        use_lane = b.max > a.max
        reactions.append(ReactionEnvelope(
            a.x, max(a.max, b.max), min(a.min, b.min),
            b.governing_position if use_lane else a.governing_position,
            b.governing_spacing if use_lane else a.governing_spacing))
    diagrams = []
    for a, b in zip(truck.reaction_diagrams, lane.reaction_diagrams):
        diagrams.append([EnvelopePoint(pa.x, max(pa.max, pb.max),
                                       min(pa.min, pb.min))
                         for pa, pb in zip(a, b)])
    return CaseResults(
        shear=combine(truck.shear, lane.shear),
        moment=combine(truck.moment, lane.moment),
        deflection=combine(truck.deflection, lane.deflection),
        reactions=reactions,
        reaction_diagrams=diagrams,
        dla_used=truck.dla_used, dla_auto=truck.dla_auto,
        dla_base=truck.dla_base, dla_multiplier=truck.dla_multiplier)


def analyze(spans: Sequence[Span], axles: Sequence[Axle],
            config: LiveLoadConfig, progress: Progress = None) -> LiveLoadResults:
    if config.truck_model == "CL-625":
        axles = preset_axles("CL-625")
    elif config.truck_model == "BCL-625":
        axles = preset_axles("BCL-625")
    validate(spans, axles, config)
    config = LiveLoadConfig(**config.__dict__)
    bcl_spacings = (build_bcl_spacings(config.bcl_subdivision)
                    if config.truck_model == "BCL-625" else [])
    configurations = []
    if bcl_spacings:
        for spacing in bcl_spacings:
            rows = [Axle(a.load, a.spacing) for a in axles]
            rows[2].spacing = spacing
            configurations.append(rows)
    else:
        configurations = [list(axles)]
    longest = max(configurations, key=lambda rows: sum(a.spacing for a in rows[:-1]))

    if progress:
        progress(0.02, "Assembling beam stiffness...")
    system = BeamSystem(spans, config)
    step, reason = compute_effective_increment(
        spans, longest, config.truck_increment, config.elems_per_span)
    positions = truck_positions(system.supports, longest, step,
                                config.lane_start, config.lane_end)
    progress and progress(0.15, f"Building influence functions ({system.n_elems} elements)...")

    udl_cache: Dict[float, Tuple[np.ndarray, np.ndarray]] = {}

    def udl(w: float):
        if w not in udl_cache:
            udl_cache[w] = system.udl_envelopes(w)
        return udl_cache[w]

    def truck_case(label: str, factor: float, w_udl: float,
                   auto_dla: bool) -> CaseResults:
        n_pos = len(positions)
        maxima = np.zeros(system.n_responses)
        minima = np.zeros(system.n_responses)
        gov_max = np.zeros(system.n_responses)
        gov_min = np.zeros(system.n_responses)
        hist_max = np.full((n_pos, system.n_supports), -np.inf)
        hist_min = np.full((n_pos, system.n_supports), np.inf)
        gov_spacing_max = np.zeros(system.n_supports)
        gov_spacing_min = np.zeros(system.n_supports)
        for idx, lead in enumerate(positions):
            if progress and idx % max(1, n_pos // 30) == 0:
                progress(0.18 + 0.64 * idx / max(1, n_pos),
                         f"{label}: truck position {idx + 1}/{n_pos}")
            local_max = np.full(system.n_responses, -np.inf)
            local_min = np.full(system.n_responses, np.inf)
            local_spacing_max = np.zeros(system.n_supports)
            local_spacing_min = np.zeros(system.n_supports)
            for ci, rows in enumerate(configurations):
                spacing = bcl_spacings[ci] if bcl_spacings else 0.0
                for direction in (rows, reverse_axles(rows)):
                    elements, xis = system._axle_locations(lead, direction)
                    vals = np.zeros((len(direction), system.n_responses))
                    for i, (e, xi) in enumerate(zip(elements, xis)):
                        if e >= 0:
                            vals[i] = _influence(system.coeffs[e], xi)
                    weights = np.array([a.load for a in direction]) * factor
                    if label == "Lane":
                        total = np.sum(vals * weights[:, None], axis=0)
                        case_max = total
                        case_min = total
                    elif not auto_dla:
                        total = np.sum(vals * weights[:, None], axis=0)
                        _, _, eff = resolve_dla(config)
                        case_max = total * (1.0 + eff)
                        case_min = case_max
                    else:
                        contrib = vals * weights[:, None]
                        pos_mask = vals > 1e-12
                        neg_mask = vals < -1e-12
                        total = contrib.sum(axis=0)
                        pos_sum = np.where(pos_mask, contrib, 0.0).sum(axis=0)
                        neg_sum = np.where(neg_mask, contrib, 0.0).sum(axis=0)
                        count_pos = pos_mask.sum(axis=0)
                        count_neg = neg_mask.sum(axis=0)
                        front_pos = (pos_mask[:3].all(axis=0) if len(direction) >= 3
                                     else np.zeros(system.n_responses, dtype=bool))
                        front_neg = (neg_mask[:3].all(axis=0) if len(direction) >= 3
                                     else np.zeros(system.n_responses, dtype=bool))
                        dla_max = _dla_vec(count_pos, front_pos)
                        dla_min = _dla_vec(count_neg, front_neg)
                        mult = max(0.0, min(1.0, float(config.dla_multiplier)))
                        case_max = total + dla_max * mult * pos_sum
                        case_min = total + dla_min * mult * neg_sum
                    better = case_max > local_max
                    local_max[better] = case_max[better]
                    local_spacing_max[better[system.reaction_offset:]] = spacing
                    better = case_min < local_min
                    local_min[better] = case_min[better]
                    local_spacing_min[better[system.reaction_offset:]] = spacing
            better = local_max > maxima
            maxima[better] = local_max[better]
            gov_max[better] = lead
            reaction_better = better[system.reaction_offset:]
            gov_spacing_max[reaction_better] = local_spacing_max[reaction_better]
            better = local_min < minima
            minima[better] = local_min[better]
            gov_min[better] = lead
            reaction_better = better[system.reaction_offset:]
            gov_spacing_min[reaction_better] = local_spacing_min[reaction_better]
            hist_max[idx] = local_max[system.reaction_offset:]
            hist_min[idx] = local_min[system.reaction_offset:]

        udl_max, udl_min = udl(w_udl)
        maxima += udl_max
        minima += udl_min
        hist_max += udl_max[system.reaction_offset:]
        hist_min += udl_min[system.reaction_offset:]

        # Refine every sampled extremum with a local 9-point search.
        if progress:
            progress(0.84, f"{label}: refining governing truck positions...")
        for r in range(system.n_responses):
            p = gov_max[r]
            lo = max(positions[0], p - step)
            hi = min(positions[-1], p + step)
            best = maxima[r]
            best_p = p
            for q in np.linspace(lo, hi, 9):
                if abs(q - p) < 1e-12:
                    continue
                candidate = _case_scalar(system, q, r, configurations, factor,
                                         config, label, auto_dla)
                if candidate[0] > best:
                    best, best_p = candidate[0], float(q)
            maxima[r] = best
            gov_max[r] = best_p

            p = gov_min[r]
            lo = max(positions[0], p - step)
            hi = min(positions[-1], p + step)
            best = minima[r]
            best_p = p
            for q in np.linspace(lo, hi, 9):
                if abs(q - p) < 1e-12:
                    continue
                candidate = _case_scalar(system, q, r, configurations, factor,
                                         config, label, auto_dla)
                if candidate[1] < best:
                    best, best_p = candidate[1], float(q)
            minima[r] = best
            gov_min[r] = best_p

        maxima = np.maximum(maxima, minima)
        shear = [EnvelopePoint(float(system.x_shear[i]), float(maxima[i]),
                               float(minima[i]))
                 for i in range(2 * system.n_elems)]
        moment = [EnvelopePoint(float(system.x_nodes[i]),
                                float(maxima[system.moment_offset + i]),
                                float(minima[system.moment_offset + i]))
                  for i in range(system.n_nodes)]
        deflection = [EnvelopePoint(float(system.x_nodes[i]),
                                    float(maxima[system.deflection_offset + i]),
                                    float(minima[system.deflection_offset + i]))
                      for i in range(system.n_nodes)]
        reactions = [
            ReactionEnvelope(
                support,
                float(maxima[system.reaction_offset + s]),
                float(minima[system.reaction_offset + s]),
                float(gov_max[system.reaction_offset + s]),
                (float(gov_spacing_max[s]) if bcl_spacings else None))
            for s, support in enumerate(system.supports)]
        diagrams = [
            [EnvelopePoint(float(positions[i]), float(hist_max[i, s]),
                           float(hist_min[i, s]))
             for i in range(n_pos)]
            for s in range(system.n_supports)]
        if label == "Lane":
            dla_used, dla_auto, dla_base, dla_mult = 0.0, False, 0.0, 1.0
        else:
            auto, base, eff = resolve_dla(config)
            dla_used = 0.0 if auto else eff
            dla_auto, dla_base, dla_mult = auto, base, config.dla_multiplier
        return CaseResults(shear, moment, deflection, reactions, diagrams,
                           dla_used, dla_auto, dla_base, dla_mult)

    truck: Optional[CaseResults] = None
    lane: Optional[CaseResults] = None
    if config.load_case in ("truck", "envelope"):
        auto = config.dla_override is None
        truck = truck_case("Truck", 1.0, 0.0, auto)
    if config.load_case in ("lane", "envelope"):
        lane = truck_case("Lane", LANE_TRUCK_FACTOR, config.lane_udl, False)
    cases: Dict[str, CaseResults] = {}
    if truck:
        cases["truck"] = truck
    if lane:
        cases["lane"] = lane
    if truck and lane:
        cases["envelope"] = _combine_cases(truck, lane)
    if config.load_case not in cases:
        raise ValueError("The selected load case was not calculated.")
    selected = cases[config.load_case]
    influence = {
        "moment_mid": system.influence_line(
            system.moment_offset + system.n_nodes // 2),
        "shear_left": system.influence_line(0),
        "reaction_0": system.influence_line(system.reaction_offset),
    }
    if progress:
        progress(1.0, "Live load analysis complete.")
    return LiveLoadResults(
        load_case=config.load_case, cases=cases, spans=list(spans),
        axles=list(axles), config=config,
        x_nodes=[float(v) for v in system.x_nodes],
        support_positions=list(system.supports),
        truck_positions=positions, increment_used=step,
        base_increment=config.truck_increment, increment_reason=reason,
        bcl_spacings=bcl_spacings, influence=influence,
        log=f"Responses: {system.n_responses}, unit-load influence solves: "
            f"{4 * system.n_elems}, UDL samples: {UDL_SAMPLES} per element.")


def _dla_vec(counts: np.ndarray, front_three: np.ndarray) -> np.ndarray:
    result = np.full(counts.shape, DLA_FACTOR, dtype=float)
    result = np.where(counts == 1, 0.40, result)
    result = np.where(counts == 2, 0.30, result)
    result = np.where((counts == 3) & front_three, 0.30, result)
    result = np.where(counts <= 0, 0.0, result)
    return result


def _case_scalar(system: BeamSystem, lead: float, response: int,
                 configurations: Sequence[Sequence[Axle]], factor: float,
                 config: LiveLoadConfig, label: str, auto_dla: bool
                 ) -> Tuple[float, float]:
    best_max = -np.inf
    best_min = np.inf
    _, _, eff = resolve_dla(config)
    for rows in configurations:
        for direction in (rows, reverse_axles(rows)):
            elements, xis = system._axle_locations(lead, direction)
            values = np.empty(len(direction))
            for i, (e, xi) in enumerate(zip(elements, xis)):
                values[i] = (0.0 if e < 0
                             else float(_influence(system.coeffs[e, response], xi)))
            weights = np.array([a.load for a in direction]) * factor
            contrib = values * weights
            if label == "Lane" or not auto_dla:
                total = float(np.sum(contrib))
                if label != "Lane":
                    total *= (1.0 + eff)
                best_max = max(best_max, total)
                best_min = min(best_min, total)
                continue
            total = float(np.sum(contrib))
            pos = values > 1e-12
            neg = values < -1e-12
            count_pos = int(np.count_nonzero(pos))
            count_neg = int(np.count_nonzero(neg))
            front_pos = len(direction) >= 3 and bool(np.all(pos[:3]))
            front_neg = len(direction) >= 3 and bool(np.all(neg[:3]))
            pos_sum = float(np.sum(contrib[pos]))
            neg_sum = float(np.sum(contrib[neg]))
            mult = max(0.0, min(1.0, float(config.dla_multiplier)))
            max_value = total + truck_group_dla(count_pos, front_pos) * mult * pos_sum
            min_value = total + truck_group_dla(count_neg, front_neg) * mult * neg_sum
            best_max = max(best_max, max_value)
            best_min = min(best_min, min_value)
    return best_max, best_min


# --------------------------------------------------------------------------- #
# import from a selected beam chain
# --------------------------------------------------------------------------- #
def chain_geometry(project, selected: Iterable[int]):
    """Order selected beam elements into a single-node-wide chain.

    Returns ``{"points": [(distance_m, xyz), ...], "element_tags": [...],
    "node_tags": [...]}`` or ``None`` when the selection is not a single line.
    """
    tags = [int(t) for t in selected if int(t) in project.elements]
    edges = []
    for tag in tags:
        e = project.elements[tag]
        if e.kind == "beam" and len(e.nodes) >= 2:
            edges.append((tag, int(e.nodes[0]), int(e.nodes[1])))
    if not edges:
        return None
    adjacency: Dict[int, List[Tuple[int, int]]] = {}
    for tag, a, b in edges:
        adjacency.setdefault(a, []).append((b, tag))
        adjacency.setdefault(b, []).append((a, tag))
    endpoints = [node for node, links in adjacency.items() if len(links) == 1]
    if len(endpoints) == 2:
        start = min(endpoints)
    elif len(endpoints) == 0:
        start = min(adjacency)
    else:
        return None
    node_path = [start]
    edge_path: List[int] = []
    used = set()
    current = start
    while len(used) < len(edges):
        options = [(nxt, tag) for nxt, tag in adjacency.get(current, [])
                   if tag not in used]
        if not options:
            break
        nxt, tag = options[0]
        used.add(tag)
        edge_path.append(tag)
        node_path.append(nxt)
        current = nxt
    if len(used) != len(edges) or len(node_path) != len(edges) + 1:
        return None
    if node_path[0] == node_path[-1]:
        return None
    points = [(0.0, project.node_xyz(node_path[0]))]
    distance = 0.0
    for i in range(1, len(node_path)):
        distance += project.element_length(
            project.elements[edge_path[i - 1]]) / 1000.0
        points.append((distance, project.node_xyz(node_path[i])))
    return {"points": points, "element_tags": edge_path,
            "node_tags": node_path}


def beam_chain_from_project(project, selected: Iterable[int]
                            ) -> Optional[Tuple[List[Span], float, float, str]]:
    """Return spans, E (Pa), I (m4) and a note for a selected beam chain."""
    tags = [int(t) for t in selected if int(t) in project.elements]
    edges = []
    for tag in tags:
        e = project.elements[tag]
        if e.kind == "beam" and len(e.nodes) >= 2:
            edges.append((tag, int(e.nodes[0]), int(e.nodes[1])))
    if not edges:
        return None
    adjacency: Dict[int, List[Tuple[int, int]]] = {}
    for tag, a, b in edges:
        adjacency.setdefault(a, []).append((b, tag))
        adjacency.setdefault(b, []).append((a, tag))
    # Largest connected component of the selected beams.
    seen = set()
    components: List[set] = []
    for node in adjacency:
        if node in seen:
            continue
        stack = [node]
        comp = set()
        seen.add(node)
        while stack:
            cur = stack.pop()
            comp.add(cur)
            for nxt, _tag in adjacency[cur]:
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        components.append(comp)
    nodes = max(components, key=len)

    def farthest(start: int) -> Tuple[int, Dict[int, int]]:
        queue = [(start, None)]
        distance = {start: 0.0}
        previous: Dict[int, Optional[int]] = {start: None}
        while queue:
            cur, parent = queue.pop(0)
            for nxt, tag in adjacency.get(cur, []):
                if nxt == parent or nxt not in nodes or nxt in distance:
                    continue
                distance[nxt] = distance[cur] + project.element_length(
                    project.elements[tag]) / 1000.0
                previous[nxt] = cur
                queue.append((nxt, cur))
        end = max(distance, key=distance.get)
        return end, previous

    start = next(iter(nodes))
    end1, _ = farthest(start)
    end2, previous = farthest(end1)
    path = []
    cur = end2
    while cur is not None:
        path.append(cur)
        cur = previous.get(cur)
    path.reverse()
    if len(path) < 2:
        return None
    support_positions = [0.0]
    distances = [0.0]
    cumulative = 0.0
    e_by_pair = {(min(a, b), max(a, b)): tag for tag, a, b in edges}
    e_tag = None
    material = None
    section = None
    for a, b in zip(path[:-1], path[1:]):
        tag = e_by_pair.get((min(a, b), max(a, b)))
        if tag is None:
            return None
        element = project.elements[tag]
        if e_tag is None:
            e_tag = tag
        cumulative += project.element_length(element) / 1000.0
        distances.append(cumulative)
        if any(project.nodes[b].support):
            support_positions.append(cumulative)
    if support_positions[-1] < cumulative - 1e-9:
        support_positions.append(cumulative)
    support_positions = sorted(set(round(v, 9) for v in support_positions))
    spans = [Span(b - a) for a, b in zip(support_positions[:-1],
                                        support_positions[1:])
             if b - a > 1e-9]
    if not spans:
        return None
    e_values = []
    i_values = []
    for tag, a, b in edges:
        if tag not in tags:
            continue
        element = project.elements[tag]
        material = project.material_of(element)
        section = project.section_of(element)
        e_values.append(float(material.E) * 1.0e9)  # kN/mm2 -> Pa
        i_values.append(float(section.Iy) * 1.0e-12)  # mm4 -> m4
    if not e_values or not i_values:
        return None
    E = sum(e_values) / len(e_values)
    I = sum(i_values) / len(i_values)
    note = (f"Beam chain: {len(edges)} element(s), {len(spans)} span(s), "
            f"{sum(s.length for s in spans):g} m; E={E / 1e9:g} GPa, "
            f"I={I:.6g} m4 (mean of the chain members).")
    return spans, E, I, note
