"""Study model — a named bundle of room description + data spec + results."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from thermal.api_models import Room, RCModelOut


def _now() -> datetime:
    return datetime.now(timezone.utc)


class DataSpec(BaseModel):
    """Signal selection and time range for fitting."""
    signals: dict[str, str | None] = Field(
        default_factory=lambda: {"T_int": None, "T_ext": None, "Q_sol": None},
        description="Mapping of role → signal name (or None if unselected).",
    )
    start: str | None = Field(default=None, description="ISO date string YYYY-MM-DD.")
    end: str | None = Field(default=None, description="ISO date string YYYY-MM-DD.")


SCHEMA_VERSION = 1


class Study(BaseModel):
    """Top-level study record persisted as user_data/{id}.json."""
    schema_version: int = Field(default=SCHEMA_VERSION, description="File format version.")
    id: str = Field(..., description="Unique study ID (UUID4 hex).")
    name: str = Field(default="New study")
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
    room: Room | None = Field(default=None)
    data_spec: DataSpec = Field(default_factory=DataSpec)
    rc_prior: RCModelOut | None = Field(default=None, description="Cached result of build_priors(room).")
    fit_result: Any = Field(default=None, description="Reserved for Phase 2 posterior.")


class StudyStub(BaseModel):
    """Lightweight row for the studies list."""
    id: str
    name: str
    updated_at: datetime
