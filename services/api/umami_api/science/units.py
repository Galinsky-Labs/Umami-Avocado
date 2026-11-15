"""Measurement ontology: units, dimensions, quantity kinds and replicate semantics (UA-005).

Units are defined by a dimension vector over SI base dimensions plus a scale (and an
offset for affine temperature scales). Conversions are only possible between units
of identical dimension; "arbitrary" units such as OD600 or pH are explicitly
non-convertible, never silently coerced.
"""
import math
from dataclasses import dataclass
from statistics import fmean, stdev

# Base dimensions: mass, length, time, amount, temperature
DIMENSIONS = ("M", "L", "T", "N", "Θ")


@dataclass(frozen=True)
class Unit:
    symbol: str
    name: str
    dimension: tuple[int, int, int, int, int]
    scale: float = 1.0          # value_in_SI = value * scale + offset
    offset: float = 0.0
    convertible: bool = True    # False for arbitrary/instrument-relative scales

    def to_si(self, value: float) -> float:
        return value * self.scale + self.offset

    def from_si(self, value: float) -> float:
        return (value - self.offset) / self.scale


DIMENSIONLESS = (0, 0, 0, 0, 0)
MASS = (1, 0, 0, 0, 0)
VOLUME = (0, 3, 0, 0, 0)
TIME = (0, 0, 1, 0, 0)
RATE = (0, 0, -1, 0, 0)
AMOUNT = (0, 0, 0, 1, 0)
MASS_CONC = (1, -3, 0, 0, 0)
MOLAR_CONC = (0, -3, 0, 1, 0)
TEMPERATURE = (0, 0, 0, 0, 1)
COUNT_CONC = (0, -3, 0, 0, 0)

_UNITS = [
    Unit("kg", "kilogram", MASS), Unit("g", "gram", MASS, 1e-3),
    Unit("mg", "milligram", MASS, 1e-6), Unit("ug", "microgram", MASS, 1e-9),
    Unit("m3", "cubic metre", VOLUME), Unit("L", "litre", VOLUME, 1e-3),
    Unit("mL", "millilitre", VOLUME, 1e-6), Unit("uL", "microlitre", VOLUME, 1e-9),
    Unit("s", "second", TIME), Unit("min", "minute", TIME, 60.0),
    Unit("h", "hour", TIME, 3600.0), Unit("d", "day", TIME, 86400.0),
    Unit("1/s", "per second", RATE), Unit("1/h", "per hour", RATE, 1 / 3600.0),
    Unit("mol", "mole", AMOUNT), Unit("mmol", "millimole", AMOUNT, 1e-3),
    Unit("umol", "micromole", AMOUNT, 1e-6),
    Unit("kg/m3", "kilogram per cubic metre", MASS_CONC), Unit("g/L", "gram per litre", MASS_CONC),
    Unit("mg/L", "milligram per litre", MASS_CONC, 1e-3),
    Unit("mg/mL", "milligram per millilitre", MASS_CONC),
    Unit("ug/mL", "microgram per millilitre", MASS_CONC, 1e-3),
    Unit("mol/m3", "mole per cubic metre", MOLAR_CONC), Unit("M", "molar", MOLAR_CONC, 1e3),
    Unit("mM", "millimolar", MOLAR_CONC), Unit("uM", "micromolar", MOLAR_CONC, 1e-3),
    Unit("K", "kelvin", TEMPERATURE), Unit("degC", "degree Celsius", TEMPERATURE, 1.0, 273.15),
    Unit("1", "dimensionless ratio", DIMENSIONLESS), Unit("%", "percent", DIMENSIONLESS, 1e-2),
    Unit("g/g", "gram per gram", DIMENSIONLESS), Unit("mg/g", "milligram per gram",
                                                      DIMENSIONLESS, 1e-3),
    Unit("CFU/mL", "colony-forming units per millilitre", COUNT_CONC, 1e6),
    Unit("OD600", "optical density at 600 nm (instrument-relative)", DIMENSIONLESS,
         convertible=False),
    Unit("pH", "pH (logarithmic)", DIMENSIONLESS, convertible=False),
    Unit("rpm", "revolutions per minute", RATE, 1 / 60.0, convertible=False),
]
UNITS: dict[str, Unit] = {unit.symbol: unit for unit in _UNITS}


@dataclass(frozen=True)
class QuantityKind:
    key: str
    label: str
    dimension: tuple[int, int, int, int, int]
    canonical_unit: str
    admissible_units: tuple[str, ...]


QUANTITY_KINDS: dict[str, QuantityKind] = {q.key: q for q in [
    QuantityKind("biomass_concentration", "Dry cell weight concentration", MASS_CONC, "g/L",
                 ("g/L", "mg/L", "mg/mL", "kg/m3")),
    QuantityKind("optical_density", "Optical density (OD600)", DIMENSIONLESS, "OD600", ("OD600",)),
    QuantityKind("glutamate_concentration", "Free glutamate concentration", MASS_CONC, "g/L",
                 ("g/L", "mg/L", "mg/mL", "ug/mL")),
    QuantityKind("nucleotide_concentration", "5'-ribonucleotide (IMP/GMP) concentration",
                 MASS_CONC, "mg/L", ("g/L", "mg/L", "ug/mL")),
    QuantityKind("substrate_concentration", "Residual substrate concentration", MASS_CONC, "g/L",
                 ("g/L", "mg/L", "mg/mL")),
    QuantityKind("protein_content", "Protein content (mass fraction)", DIMENSIONLESS, "%",
                 ("%", "g/g", "mg/g", "1")),
    QuantityKind("biomass_yield", "Biomass yield on substrate", DIMENSIONLESS, "g/g",
                 ("g/g", "%", "1")),
    QuantityKind("specific_growth_rate", "Specific growth rate", RATE, "1/h", ("1/h", "1/s")),
    QuantityKind("temperature", "Temperature", TEMPERATURE, "degC", ("degC", "K")),
    QuantityKind("ph", "pH", DIMENSIONLESS, "pH", ("pH",)),
    QuantityKind("elapsed_time", "Elapsed time", TIME, "h", ("h", "min", "s", "d")),
    QuantityKind("viable_count", "Viable cell count", COUNT_CONC, "CFU/mL", ("CFU/mL",)),
]}


class UnitError(ValueError):
    pass


def unit(symbol: str) -> Unit:
    try:
        return UNITS[symbol]
    except KeyError:
        raise UnitError("Unknown unit.") from None


def convert(value: float, source: str, target: str) -> float:
    if not math.isfinite(value):
        raise UnitError("Values must be finite numbers.")
    a, b = unit(source), unit(target)
    if a.symbol == b.symbol:
        return value
    if not (a.convertible and b.convertible):
        raise UnitError("Instrument-relative or logarithmic units are not convertible.")
    if a.dimension != b.dimension:
        raise UnitError("Units have incompatible dimensions.")
    return b.from_si(a.to_si(value))


def check_admissible(kind_key: str, unit_symbol: str) -> QuantityKind:
    kind = QUANTITY_KINDS.get(kind_key)
    if kind is None:
        raise UnitError("Unknown quantity kind.")
    if unit_symbol not in kind.admissible_units:
        raise UnitError("Unit is not admissible for this quantity kind.")
    return kind


@dataclass(frozen=True)
class Observation:
    value: float
    biological_replicate: int
    technical_replicate: int


@dataclass(frozen=True)
class Summary:
    mean: float | None
    sd: float | None
    n_biological: int
    n_technical: int


def summarize(observations: list[Observation]) -> Summary:
    """Nested replicate summary.

    Technical replicates (repeated measurement of one sample) are averaged first; the
    mean and sample standard deviation are then taken across *biological* replicates
    (independent cultures). Technical replicates never inflate n.
    """
    groups: dict[int, list[float]] = {}
    for obs in observations:
        groups.setdefault(obs.biological_replicate, []).append(obs.value)
    if not groups:
        return Summary(None, None, 0, 0)
    per_bio = [fmean(values) for _, values in sorted(groups.items())]
    sd = stdev(per_bio) if len(per_bio) > 1 else None
    return Summary(mean=fmean(per_bio), sd=sd, n_biological=len(per_bio),
                   n_technical=len(observations))
