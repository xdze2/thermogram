"""
Stage 1 — golden-value prior tests.

Pins the current behaviour of `build_priors` on the three describable test cases
(caravan, house, passive) BEFORE the modular channel/module refactor (Stage 2).

Two layers of protection:

  1. Hand-computed `mu`/`sigma` assertions per parameter (this file). The expected
     numbers were derived independently from the ISO 6946 / material formulas — NOT
     read off `priors.py` — so they catch a physics/intent error, not just "the code
     equals itself". See `docs/todo_modular_rc.md` Stage 1.
  2. Full `RCModelOut` JSON snapshots in `tests/snapshots/` for byte-diffing. Stage 2
     must keep these byte-identical: that is the contract that the channel/module
     refactor preserves current physics.

Scope (per `docs/test_cases.md`): cave and earthship are Stage-0-only — they need
ground/interior-solar physics not yet in `priors.py` — so they are NOT fixtured here.

KNOWN CURRENT BEHAVIOUR pinned deliberately (faithful, not necessarily ideal):
  - `alpha_eff` includes floors (incl. ground-contact) in the area-weighted average;
    only windows are excluded. A buried floor has no sol-air solar drive, yet pulls
    weight here. Fix is deferred to Stage 2 (where the snapshot delta will be visible).
  - Ground-contact floors use ISO 6946 surface resistances only (Rso=0), with no
    T_ground model — so floor U is the bare-stack value.

Units note: `C_wall.mu` / `C_room.mu` are returned in J/K even though the `unit`
field reads "MJ/K" (the frontend scales for display).
"""

import json
from pathlib import Path

import pytest

from thermal.api_models import Room
from thermal.priors import build_priors

FIXTURES = Path(__file__).parent / "fixtures"
SNAPSHOTS = Path(__file__).parent / "snapshots"

# Tight tolerance: the literals below are the full-precision independently-derived
# values, so this only guards against float-representation noise.
RTOL = 1e-9


def load_room(name: str) -> Room:
    return Room(**json.loads((FIXTURES / f"{name}.json").read_text()))


# Hand-computed expected (mu, sigma) per parameter, independently derived from the
# ISO 6946 series resistance + material rho·cp·d formulas. See module docstring.
EXPECTED = {
    "caravan": {
        "H_env":     (14.383530148619984, 0.9340558689092204),
        "H_ve":      (10.6336, 3.161462673130904),
        "C_wall":    (0.0, 0.0),
        "C_room":    (240000.0, 144000.0),
        "alpha_eff": (0.65, 0.06495190528383289),
    },
    "house": {
        "H_env":     (36.97207731941005, 2.734035990524928),
        "H_ve":      (33.8, 7.054643860606998),
        "C_wall":    (46672800.0, 5899633.806644273),
        "C_room":    (800000.0, 480000.0),
        "alpha_eff": (0.6285714285714286, 0.06583839212458807),
    },
    "passive": {
        "H_env":     (16.497465864509987, 1.2065106961365142),
        "H_ve":      (9.8, 1.5574337867145431),
        "C_wall":    (46672800.0, 5899633.806644273),
        "C_room":    (800000.0, 480000.0),
        "alpha_eff": (0.6285714285714286, 0.06583839212458807),
    },
}

CASES = sorted(EXPECTED.keys())


def _params(out):
    return {
        "H_env": out.H_env,
        "H_ve": out.H_ve,
        "C_wall": out.C_wall,
        "C_room": out.C_room,
        "alpha_eff": out.alpha_eff,
    }


@pytest.mark.parametrize("case", CASES)
def test_golden_mu_sigma(case):
    out = build_priors(load_room(case))
    params = _params(out)
    for symbol, (exp_mu, exp_sigma) in EXPECTED[case].items():
        p = params[symbol]
        assert p.mu == pytest.approx(exp_mu, rel=RTOL, abs=1e-9), f"{case}.{symbol}.mu"
        assert p.sigma == pytest.approx(exp_sigma, rel=RTOL, abs=1e-9), f"{case}.{symbol}.sigma"


@pytest.mark.parametrize("case", CASES)
def test_contributions_sum_to_mu(case):
    """Additive parameters: sum(contribution values) == mu.

    Two parameters are NOT additive breakdowns and are excluded:
      - alpha_eff is an area-weighted *average*; each contribution carries the
        element's raw absorptivity, so they don't sum to mu.
      - H_ve.mu = ventilation term + window losses, but its ventilation contribution
        carries the vent-only value; the window contributions make up the rest, so the
        total still equals mu (verified here — H_ve stays in the additive set).
    """
    out = build_priors(load_room(case))
    for symbol, p in _params(out).items():
        if symbol == "alpha_eff":
            continue
        total = sum(c.value for c in p.contributions)
        assert total == pytest.approx(p.mu, rel=1e-9, abs=1e-9), f"{case}.{symbol}"


@pytest.mark.parametrize("case", CASES)
def test_snapshot_byte_identical(case):
    """The Stage 2 contract: RCModelOut JSON must stay byte-for-byte unchanged.

    Regenerate intentionally with `tests/regen_snapshots.py` only when a behaviour
    change is deliberate, and review the diff.
    """
    out = build_priors(load_room(case))
    current = json.dumps(out.model_dump(), indent=2, sort_keys=True) + "\n"
    expected = (SNAPSHOTS / f"{case}.json").read_text()
    assert current == expected, (
        f"{case} snapshot drift — if intentional, regenerate and review the diff"
    )


def test_caravan_has_no_storage():
    """Caravan is all-light: STORAGE channel is empty, so C_wall collapses to zero."""
    out = build_priors(load_room("caravan"))
    assert out.C_wall.mu == 0.0
    assert out.C_wall.sigma == 0.0
    assert out.C_wall.contributions == []


def test_passive_better_insulated_than_house():
    """Cross-case physical sanity: same shape, passive has far lower envelope loss."""
    house = build_priors(load_room("house"))
    passive = build_priors(load_room("passive"))
    assert passive.H_env.mu < house.H_env.mu
    assert passive.H_ve.mu < house.H_ve.mu
