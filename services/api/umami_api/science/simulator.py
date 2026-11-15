"""Deterministic yeast batch-culture simulator (UA-010).

Everything produced here is SIMULATED. It is a teaching-grade Monod model for
exercising the platform end to end, not a calibrated digital twin, and its output
must never be presented as a measured result.

Model (explicit Euler, 0.01 h step):
    mu  = mu_max * S / (Ks + S) * f_T(T) * f_pH(pH)
    dX  = mu * X
    dS  = -dX / Y_xs
    dP  = alpha * dX              (free glutamate, Luedeking-Piret growth-associated)
Temperature uses the cardinal temperature model (Rosso 1993) and pH a bounded
Gaussian response. Biological replicates perturb mu_max; technical replicates add
multiplicative measurement noise. A seeded PRNG makes runs bit-for-bit repeatable.
"""
import math
import random
from dataclasses import dataclass

MODEL_VERSION = "monod-batch-1"

MU_MAX = 0.45       # 1/h, S. cerevisiae on glucose, aerobic (typical literature order)
KS = 0.25           # g/L
Y_XS = 0.48         # g biomass / g glucose (respiratory upper bound)
ALPHA = 0.012       # g glutamate / g biomass formed
T_MIN, T_OPT, T_MAX = 5.0, 30.0, 42.0
PH_OPT, PH_WIDTH = 5.0, 1.2
BIO_CV, TECH_CV = 0.03, 0.02
STEP_H = 0.01


@dataclass(frozen=True)
class Design:
    temperature_c: float
    ph: float
    initial_glucose_g_l: float
    initial_biomass_g_l: float
    duration_h: float
    sample_interval_h: float
    biological_replicates: int
    technical_replicates: int
    seed: int


@dataclass(frozen=True)
class Sample:
    quantity: str            # biomass_concentration | substrate_concentration | glutamate_concentration
    unit: str
    time_h: float
    biological_replicate: int
    technical_replicate: int
    value: float


def temperature_factor(t: float) -> float:
    if t <= T_MIN or t >= T_MAX:
        return 0.0
    numerator = (t - T_MAX) * (t - T_MIN) ** 2
    denominator = (T_OPT - T_MIN) * ((T_OPT - T_MIN) * (t - T_OPT)
                                     - (T_OPT - T_MAX) * (T_OPT + T_MIN - 2 * t))
    return max(0.0, min(1.0, numerator / denominator))


def ph_factor(ph: float) -> float:
    return math.exp(-((ph - PH_OPT) / PH_WIDTH) ** 2)


def trajectory(design: Design, mu_max: float) -> list[tuple[float, float, float, float]]:
    """Noise-free (t, X, S, P) at each sample time."""
    x, s, p = design.initial_biomass_g_l, design.initial_glucose_g_l, 0.0
    f = temperature_factor(design.temperature_c) * ph_factor(design.ph)
    steps_per_sample = max(1, round(design.sample_interval_h / STEP_H))
    total_steps = round(design.duration_h / STEP_H)
    points = [(0.0, x, s, p)]
    for step in range(1, total_steps + 1):
        mu = mu_max * s / (KS + s) * f
        dx = min(mu * x * STEP_H, s * Y_XS)  # cannot consume more substrate than present
        x, s, p = x + dx, max(0.0, s - dx / Y_XS), p + ALPHA * dx
        if step % steps_per_sample == 0 or step == total_steps:
            points.append((round(step * STEP_H, 4), x, s, p))
    return points


def simulate(design: Design) -> list[Sample]:
    rng = random.Random(design.seed)
    samples: list[Sample] = []
    for bio in range(1, design.biological_replicates + 1):
        mu_max = MU_MAX * max(0.5, rng.gauss(1.0, BIO_CV))
        for t, x, s, p in trajectory(design, mu_max):
            for quantity, unit, value in (("biomass_concentration", "g/L", x),
                                          ("substrate_concentration", "g/L", s),
                                          ("glutamate_concentration", "g/L", p)):
                for tech in range(1, design.technical_replicates + 1):
                    noisy = max(0.0, value * rng.gauss(1.0, TECH_CV))
                    samples.append(Sample(quantity, unit, t, bio, tech, round(noisy, 6)))
    return samples


def summarize_final(samples: list[Sample]) -> dict:
    """Mean of the final time point per quantity across all replicates."""
    final_t = max(sample.time_h for sample in samples)
    out: dict[str, float] = {}
    for quantity in ("biomass_concentration", "substrate_concentration", "glutamate_concentration"):
        values = [s.value for s in samples if s.quantity == quantity and s.time_h == final_t]
        out[quantity] = round(sum(values) / len(values), 4)
    out["final_time_h"] = final_t
    return out
