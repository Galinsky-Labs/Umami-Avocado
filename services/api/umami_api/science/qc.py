"""Scientific normalization, reproducibility and quality control (UA-016).

All checks are deterministic functions of stored measurements (canonical units).
They flag data for human review; they never delete or alter measurements.
"""
import math
from dataclasses import dataclass
from statistics import fmean, median, stdev

CV_LIMIT = 0.20            # between-biological-replicate coefficient of variation
ROBUST_Z_LIMIT = 3.5       # modified z-score (Iglewicz & Hoaglin) for outliers
MIN_BIO_REPLICATES = 3
PLAUSIBLE = {              # canonical-unit plausibility bounds per quantity kind
    "biomass_concentration": (0.0, 300.0),      # g/L
    "glutamate_concentration": (0.0, 100.0),    # g/L
    "nucleotide_concentration": (0.0, 50000.0),  # mg/L
    "substrate_concentration": (0.0, 600.0),    # g/L
    "protein_content": (0.0, 100.0),            # %
    "biomass_yield": (0.0, 1.0),                # g/g
    "specific_growth_rate": (0.0, 2.0),         # 1/h
    "temperature": (-20.0, 130.0),              # degC
    "ph": (0.0, 14.0),
}


@dataclass(frozen=True)
class Point:
    id: str
    sample: str
    bio: int
    tech: int
    value: float


def robust_z(values: list[float]) -> list[float]:
    if len(values) < 3:
        return [0.0] * len(values)
    m = median(values)
    mad = median(abs(v - m) for v in values)
    if mad == 0:
        return [0.0] * len(values)
    return [0.6745 * (v - m) / mad for v in values]


def evaluate(points: list[Point], quantity_kind: str) -> dict:
    flags: list[dict] = []
    low, high = PLAUSIBLE.get(quantity_kind, (-math.inf, math.inf))
    for p in points:
        if not (low <= p.value <= high):
            flags.append({"severity": "error", "check": "plausible_range", "measurement": p.id,
                          "sample": p.sample, "message": f"Outside plausible range "
                          f"[{low:g}, {high:g}] for {quantity_kind}."})
    samples: dict[str, dict[int, list[Point]]] = {}
    for p in points:
        samples.setdefault(p.sample, {}).setdefault(p.bio, []).append(p)
    cvs = []
    for sample, bios in sorted(samples.items()):
        means = {bio: fmean(x.value for x in pts) for bio, pts in bios.items()}
        if len(means) < MIN_BIO_REPLICATES:
            flags.append({"severity": "warning", "check": "replication", "sample": sample,
                          "message": f"Only {len(means)} biological replicate(s)."})
        if len(means) > 1:
            mean = fmean(means.values())
            if mean > 0:
                cv = stdev(means.values()) / mean
                cvs.append(cv)
                if cv > CV_LIMIT:
                    flags.append({"severity": "warning", "check": "replicate_cv",
                                  "sample": sample, "message": f"CV {cv:.0%} exceeds "
                                  f"{CV_LIMIT:.0%}."})
            ordered = sorted(means)
            for bio, z in zip(ordered, robust_z([means[b] for b in ordered]), strict=True):
                if abs(z) > ROBUST_Z_LIMIT:
                    flags.append({"severity": "warning", "check": "outlier", "sample": sample,
                                  "biological_replicate": bio,
                                  "message": f"Robust z-score {z:.1f}."})
    errors = sum(f["severity"] == "error" for f in flags)
    warnings = sum(f["severity"] == "warning" for f in flags)
    return {
        "status": "fail" if errors else ("warn" if warnings else "pass"),
        "flags": flags[:500],
        "metrics": {"measurements": len(points), "samples": len(samples),
                    "median_cv": round(median(cvs), 4) if cvs else None,
                    "max_cv": round(max(cvs), 4) if cvs else None,
                    "errors": errors, "warnings": warnings},
    }


def biomass_yield(x0: float, x_final: float, s0: float, s_final: float) -> float | None:
    """Apparent biomass yield on substrate (g/g); None when no substrate was consumed."""
    consumed = s0 - s_final
    if consumed <= 1e-9:
        return None
    return (x_final - x0) / consumed


def reproducibility(final_values: list[float]) -> dict:
    """Between-run agreement of a final-time endpoint for runs sharing a design."""
    if len(final_values) < 2:
        return {"runs": len(final_values), "cv": None, "reproducible": None}
    mean = fmean(final_values)
    cv = stdev(final_values) / mean if mean else None
    return {"runs": len(final_values), "mean": round(mean, 6),
            "cv": round(cv, 6) if cv is not None else None,
            "reproducible": cv is not None and cv <= CV_LIMIT}
