"""
Stage 2b — assembler tests: the exactly-once ownership invariant, and parity of the
assembled prior with the legacy `build_priors` output (so 2c wiring is a no-op).
"""

import json
from pathlib import Path

import pytest

from thermal.api_models import Room
from thermal.assembler import (
    assemble,
    collect_priors,
    module_catalogue,
    active_modules,
    _assert_exactly_once,
)
import thermal.assembler as A
from thermal.channels import CONDUCTION_EXT, element_channels
from thermal import modules as M
from thermal.priors import build_priors

FIXTURES = Path(__file__).parent / "fixtures"
CASES = ["caravan", "house", "passive"]


def load_room(name: str) -> Room:
    return Room(**json.loads((FIXTURES / f"{name}.json").read_text()))


@pytest.mark.parametrize("case", CASES)
def test_assemble_exactly_once(case):
    """Assembly succeeds — every (element, channel) cell owned exactly once."""
    room = load_room(case)
    assemble(room)  # raises AssertionError on any double/unclaimed/stray cell


def test_double_claim_is_hard_error():
    """A second module claiming the same cell must fail the invariant."""
    room = load_room("caravan")
    mods = assemble(room)
    # Duplicate the first opaque element's HeavyWall to force a double-claim.
    heavy = next(m for m in mods if isinstance(m, M.HeavyWall))
    with pytest.raises(AssertionError, match="more than once"):
        _assert_exactly_once(mods + [heavy], room)


def test_unclaimed_cell_is_hard_error():
    """Dropping a module that owns a cell must fail the invariant."""
    room = load_room("caravan")
    mods = assemble(room)
    heavy = next(m for m in mods if isinstance(m, M.HeavyWall))
    with pytest.raises(AssertionError, match="unclaimed"):
        _assert_exactly_once([m for m in mods if m is not heavy], room)


@pytest.mark.parametrize("case", CASES)
def test_assembled_prior_matches_legacy(case):
    """The assembled prior must equal the legacy build_priors output exactly."""
    room = load_room(case)
    assembled = collect_priors(assemble(room), room)
    legacy = build_priors(room)
    assert assembled.model_dump() == legacy.model_dump()


# ---------------------------------------------------------------------------
# Stage 5 — module reporting
# ---------------------------------------------------------------------------

def test_catalogue_covers_every_assembled_class():
    """Every module the assembler can emit has a catalogue entry (no KeyError at report)."""
    cat = {m.name for m in module_catalogue()}
    for case in CASES:
        for mod in assemble(load_room(case)):
            assert type(mod).__name__ in cat


def test_active_modules_dedupes_and_counts_states():
    """House (6 heavy walls) reports ONE HeavyWall and a 2-state aggregated topology."""
    report = active_modules(assemble(load_room("house")))
    names = [m.name for m in report.modules]
    assert names.count("HeavyWall") == 1          # deduped by class
    assert report.n_states == 2                   # room + one aggregated wall node
    assert report.signals_required == ["T_ext", "T_sa", "Q_room"]


def test_caravan_has_no_extra_state():
    """All-light caravan: no STORAGE channel → no mass node → single room state."""
    report = active_modules(assemble(load_room("caravan")))
    assert report.n_states == 1
    heavy = next(m for m in report.modules if m.name == "HeavyWall")
    assert heavy.extra_states == []               # light instance narrows away T_wall


def test_identifiability_warning_fires_over_limit(monkeypatch):
    """The warning is a FIT concern: trips when free params exceed the sensor limit."""
    monkeypatch.setattr(A, "_FIT_PARAM_LIMIT", 2)
    report = active_modules(assemble(load_room("house")))
    assert report.n_free_params > 2
    assert report.identifiability_warning is not None
    assert "FITTING" in report.identifiability_warning
