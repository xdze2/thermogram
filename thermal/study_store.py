"""CRUD for Study records stored as JSON files in user_data/."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from thermal.study import Study, StudyStub, SCHEMA_VERSION

_DATA_DIR = Path(__file__).parent.parent / "user_data"


def _ensure_dir() -> Path:
    _DATA_DIR.mkdir(exist_ok=True)
    return _DATA_DIR


def _path(study_id: str) -> Path:
    return _DATA_DIR / f"{study_id}.json"


def list_studies() -> list[StudyStub]:
    d = _ensure_dir()
    stubs = []
    for f in sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            s = Study.model_validate_json(f.read_text())
            stubs.append(StudyStub(id=s.id, name=s.name, updated_at=s.updated_at))
        except Exception:
            pass
    return stubs


def load_study(study_id: str) -> Study:
    p = _path(study_id)
    if not p.exists():
        raise KeyError(study_id)
    study = Study.model_validate_json(p.read_text())
    if study.schema_version != SCHEMA_VERSION:
        raise ValueError(
            f"Study {study_id} has schema_version={study.schema_version}, "
            f"expected {SCHEMA_VERSION}. Manual migration required."
        )
    return study


def save_study(study: Study) -> None:
    _ensure_dir()
    study.updated_at = datetime.now(timezone.utc)
    _path(study.id).write_text(study.model_dump_json(indent=2))


def create_study(name: str = "New study") -> Study:
    study = Study(id=uuid.uuid4().hex, name=name)
    save_study(study)
    return study


def delete_study(study_id: str) -> None:
    p = _path(study_id)
    if not p.exists():
        raise KeyError(study_id)
    p.unlink()


def duplicate_study(study_id: str) -> Study:
    original = load_study(study_id)
    copy = original.model_copy(
        update={
            "id": uuid.uuid4().hex,
            "name": f"{original.name} (copy)",
        }
    )
    save_study(copy)
    return copy
