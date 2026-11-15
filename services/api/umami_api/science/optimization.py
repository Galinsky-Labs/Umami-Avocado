"""Bounded next-experiment selection (UA-020).

A small Gaussian-process surrogate (RBF kernel, pure Python) is fitted to completed runs
of ONE origin, then an upper-confidence-bound acquisition picks a batch from a bounded
candidate grid, with a minimum spacing so a batch explores distinct conditions. With fewer
than three observations it returns a deterministic space-filling design instead.
Every suggestion lies inside the caller's box, which must itself lie inside the
simulator/protocol limits. Suggestions are advice: running them is a separate, authorized,
SIMULATED-only action.
"""
import itertools
import math
from dataclasses import dataclass

LIMITS = {"temperature_c": (4.0, 45.0), "ph": (3.0, 8.0), "initial_glucose_g_l": (1.0, 150.0)}
DIMENSIONS = tuple(LIMITS)
GRID = 9


@dataclass(frozen=True)
class Observation:
    x: dict[str, float]
    y: float


@dataclass(frozen=True)
class Suggestion:
    x: dict[str, float]
    predicted_mean: float | None
    predicted_sd: float | None
    acquisition: float | None
    reason: str


def validate_bounds(bounds: dict[str, tuple[float, float]]) -> dict[str, tuple[float, float]]:
    out = {}
    for dim in DIMENSIONS:
        lo, hi = bounds.get(dim, LIMITS[dim])
        lim_lo, lim_hi = LIMITS[dim]
        if not (lim_lo <= lo <= hi <= lim_hi):
            raise ValueError(f"Bounds for {dim} must lie within [{lim_lo}, {lim_hi}].")
        out[dim] = (float(lo), float(hi))
    return out


def _unit(x: dict[str, float], bounds) -> list[float]:
    return [(x[d] - bounds[d][0]) / ((bounds[d][1] - bounds[d][0]) or 1.0) for d in DIMENSIONS]


def _kernel(a: list[float], b: list[float], length: float) -> float:
    return math.exp(-sum((p - q) ** 2 for p, q in zip(a, b, strict=True)) / (2 * length ** 2))


def _cholesky(matrix: list[list[float]]) -> list[list[float]]:
    n = len(matrix)
    lower = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1):
            s = matrix[i][j] - sum(lower[i][k] * lower[j][k] for k in range(j))
            if i == j:
                lower[i][j] = math.sqrt(max(s, 1e-12))
            else:
                lower[i][j] = s / lower[j][j]
    return lower


def _solve_lower(lower, b):
    out = []
    for i, row in enumerate(lower):
        out.append((b[i] - sum(row[k] * out[k] for k in range(i))) / row[i])
    return out


def _solve_upper(lower, b):
    n = len(lower)
    out = [0.0] * n
    for i in reversed(range(n)):
        out[i] = (b[i] - sum(lower[k][i] * out[k] for k in range(i + 1, n))) / lower[i][i]
    return out


class GaussianProcess:
    def __init__(self, xs: list[list[float]], ys: list[float], length: float = 0.3,
                 noise: float = 1e-3):
        self.xs, self.length = xs, length
        self.mean = sum(ys) / len(ys)
        spread = math.sqrt(sum((y - self.mean) ** 2 for y in ys) / len(ys)) or 1.0
        self.scale = spread
        z = [(y - self.mean) / spread for y in ys]
        k = [[_kernel(a, b, length) + (noise if i == j else 0.0) for j, b in enumerate(xs)]
             for i, a in enumerate(xs)]
        self.lower = _cholesky(k)
        self.alpha = _solve_upper(self.lower, _solve_lower(self.lower, z))

    def predict(self, x: list[float]) -> tuple[float, float]:
        ks = [_kernel(x, b, self.length) for b in self.xs]
        mu = sum(k * a for k, a in zip(ks, self.alpha, strict=True))
        v = _solve_lower(self.lower, ks)
        var = max(1.0 - sum(t * t for t in v), 1e-12)
        return self.mean + mu * self.scale, math.sqrt(var) * self.scale


def candidates(bounds) -> list[dict[str, float]]:
    axes = [[bounds[d][0] + (bounds[d][1] - bounds[d][0]) * i / (GRID - 1) for i in range(GRID)]
            for d in DIMENSIONS]
    return [dict(zip(DIMENSIONS, (round(v, 3) for v in combo), strict=True))
            for combo in itertools.product(*axes)]


def suggest(observations: list[Observation], bounds: dict[str, tuple[float, float]],
            batch_size: int, beta: float = 2.0, min_spacing: float = 0.15) -> list[Suggestion]:
    bounds = validate_bounds(bounds)
    if not 1 <= batch_size <= 6:
        raise ValueError("batch_size must be between 1 and 6.")
    pool = candidates(bounds)
    tested = [_unit(o.x, bounds) for o in observations]
    chosen: list[Suggestion] = []
    chosen_units: list[list[float]] = []

    def far_enough(u):
        return all(math.dist(u, c) >= min_spacing for c in chosen_units + tested)

    if len(observations) < 3:
        # Deterministic maximin space-filling: start at the box centre, then the farthest point.
        centre = {d: round((lo + hi) / 2, 3) for d, (lo, hi) in bounds.items()}
        pool = sorted(pool, key=lambda x: math.dist(_unit(x, bounds), _unit(centre, bounds)))
        while len(chosen) < batch_size:
            pick = max(pool, key=lambda x: min([math.dist(_unit(x, bounds), c)
                                                for c in chosen_units + tested] or
                                               [-math.dist(_unit(x, bounds),
                                                           _unit(centre, bounds))]))
            chosen_units.append(_unit(pick, bounds))
            chosen.append(Suggestion(pick, None, None, None,
                                     "space-filling (n<3 observations)"))
        return chosen
    model = GaussianProcess(tested, [o.y for o in observations])
    scored = []
    for x in pool:
        u = _unit(x, bounds)
        mean, sd = model.predict(u)
        scored.append((mean + beta * sd, mean, sd, x, u))
    scored.sort(key=lambda s: (-s[0], tuple(s[3].values())))
    for acq, mean, sd, x, u in scored:
        if len(chosen) == batch_size:
            break
        if far_enough(u):
            chosen_units.append(u)
            chosen.append(Suggestion(x, round(mean, 6), round(sd, 6), round(acq, 6),
                                     f"GP-UCB (beta={beta})"))
    return chosen
