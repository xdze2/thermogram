"""
Stage 2b — assembler tests: the exactly-once ownership invariant, and parity of the
assembled prior with the legacy `build_priors` output (so 2c wiring is a no-op).
"""

import json
from pathlib import Path

import pytest

from thermal.api_models import Room
from thermal.assembler import assemble, collect_priors, _assert_exactly_once
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
