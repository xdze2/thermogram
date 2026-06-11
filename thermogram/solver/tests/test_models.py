"""The Pydantic models in thermogram.models are the canonical data contract.

These tests pin them to the *real* data files and the live ``expand()`` output,
so the models cannot silently drift from reality the way the hand-written JSON
Schemas (formerly under ``schema/``, now dropped) did. If a house file or
expand() grows a field, a model must learn about it (or explicitly allow it) —
these tests force that.
"""

from __future__ import annotations

import glob
import json
from pathlib import Path

import pytest

from thermogram.models import AtomicModel, House, Material
from thermogram.solver.physics import expand

_REPO_ROOT = Path(__file__).resolve().parents[3]
_FIXTURES = Path(__file__).parent / "fixtures"


def _is_atomic(raw: dict) -> bool:
    return "nodes" in raw and "rooms" not in raw


def _house_files() -> list[str]:
    return sorted(
        p
        for p in glob.glob(str(_REPO_ROOT / "data" / "houses" / "*.json"))
        + glob.glob(str(_FIXTURES / "*.json"))
        if not _is_atomic(json.loads(Path(p).read_text()))
    )


def _atomic_files() -> list[str]:
    return sorted(
        p
        for p in glob.glob(str(_FIXTURES / "*.json"))
        if _is_atomic(json.loads(Path(p).read_text()))
    )


@pytest.mark.parametrize("path", _house_files())
def test_real_houses_validate(path: str) -> None:
    House.model_validate(json.loads(Path(path).read_text()))


@pytest.mark.parametrize("path", _atomic_files())
def test_atomic_fixtures_validate(path: str) -> None:
    AtomicModel.model_validate(json.loads(Path(path).read_text()))


@pytest.mark.parametrize("path", glob.glob(str(_REPO_ROOT / "data" / "materials" / "*.json")))
def test_materials_validate(path: str) -> None:
    raw = json.loads(Path(path).read_text())
    for entry in raw if isinstance(raw, list) else [raw]:
        Material.model_validate(entry)


def test_expand_output_validates_as_atomic_model() -> None:
    """expand(house) must produce a valid AtomicModel."""
    house = json.loads((_FIXTURES / "maison_test.json").read_text())
    atomic_model, _ = expand(house)
    AtomicModel.model_validate(atomic_model)


def test_house_roundtrips_through_solver() -> None:
    """A House dumped back to a dict drives expand() identically — the solver can
    keep reading plain dicts at the boundary."""
    raw = json.loads((_FIXTURES / "maison_test.json").read_text())
    dumped = House.model_validate(raw).model_dump(by_alias=True, exclude_none=True)
    assert expand(dumped)[0]["nodes"] == expand(raw)[0]["nodes"]
