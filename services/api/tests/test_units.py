import math

import pytest

from umami_api.science.units import (
    QUANTITY_KINDS,
    UNITS,
    Observation,
    UnitError,
    check_admissible,
    convert,
    summarize,
)


@pytest.mark.parametrize(("value", "source", "target", "expected"), [
    (1.0, "g/L", "mg/L", 1000.0), (2.5, "mg/mL", "g/L", 2.5), (1.0, "h", "min", 60.0),
    (0.36, "1/h", "1/s", 1e-4), (30.0, "degC", "K", 303.15), (303.15, "K", "degC", 30.0),
    (50.0, "%", "g/g", 0.5), (1.0, "M", "mM", 1000.0), (5.0, "OD600", "OD600", 5.0),
])
def test_conversions(value, source, target, expected):
    assert math.isclose(convert(value, source, target), expected, rel_tol=1e-12, abs_tol=1e-12)


@pytest.mark.parametrize(("source", "target"), [
    ("g/L", "mM"), ("OD600", "g/L"), ("pH", "1"), ("h", "g"), ("g", "furlong"),
])
def test_incompatible_or_unknown_conversions_fail(source, target):
    with pytest.raises(UnitError):
        convert(1.0, source, target)


def test_non_finite_values_are_rejected():
    with pytest.raises(UnitError):
        convert(float("nan"), "g", "mg")


def test_every_quantity_kind_uses_registered_dimension_consistent_units():
    for kind in QUANTITY_KINDS.values():
        assert kind.canonical_unit in kind.admissible_units
        for symbol in kind.admissible_units:
            assert UNITS[symbol].dimension == kind.dimension
    with pytest.raises(UnitError):
        check_admissible("biomass_concentration", "OD600")


def test_nested_replicate_summary_does_not_inflate_n_with_technical_replicates():
    observations = [Observation(10, 1, 1), Observation(12, 1, 2),  # bio 1 mean 11
                    Observation(13, 2, 1),                          # bio 2 mean 13
                    Observation(15, 3, 1), Observation(15, 3, 2)]   # bio 3 mean 15
    result = summarize(observations)
    assert result.n_biological == 3 and result.n_technical == 5
    assert result.mean == 13
    assert math.isclose(result.sd, 2.0)
    single = summarize([Observation(1, 1, 1), Observation(3, 1, 2)])
    assert single.mean == 2 and single.sd is None
    assert summarize([]).mean is None
