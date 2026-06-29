"""
Model-management endpoints: list, create, rename, delete, and load from example.

New routes (all under /api):
  GET    /models                     -> list[{uid, name}]
  POST   /models                     {name?} -> {uid, name}
  POST   /models/from_example        {example_key, name?} -> {uid, name}
  GET    /models/examples            -> list[{key, name}]
  PATCH  /models/{uid}               {name} -> {uid, name}
  DELETE /models/{uid}               204

The ``examples`` module (``src/thnodes/examples.py``) may not exist yet; the
import is guarded and affected endpoints return HTTP 503 until it lands.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, HTTPException, status

from ..models import (
    ExampleInfo,
    ModelCreateIn,
    ModelFromExampleIn,
    ModelInfo,
    ModelRenameIn,
    RoomDoc,
)
from ..store import (
    _store,
    delete_model_file,
    roomdoc_from_dict,
    save_model,
)

router = APIRouter()

# ── lazy examples import ───────────────────────────────────────────────────────

def _list_examples() -> list[dict]:
    """Return [{key, name}] from examples.py, or [] if module not yet available."""
    try:
        from ...examples import list_examples  # type: ignore[import]
        return list_examples()
    except ImportError:
        return []


def _load_example(key: str) -> dict | None:
    """
    Return the example dict for *key*, or None if the module is not available.

    Raises ``HTTPException(404)`` when the module is present but *key* is
    unknown, so callers get a clear error rather than an unhandled 500.
    """
    try:
        from ...examples import load_example  # type: ignore[import]
        return load_example(key)
    except ImportError:
        return None
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc


# ── list all models ────────────────────────────────────────────────────────────

@router.get("/models", response_model=list[ModelInfo])
def list_models() -> list[ModelInfo]:
    """Return summary (uid + name) for every model in the session store."""
    return [ModelInfo(uid=doc.uid, name=doc.name) for doc in _store.values() if doc.uid]


# ── create empty model ─────────────────────────────────────────────────────────

@router.post("/models", status_code=status.HTTP_201_CREATED, response_model=ModelInfo)
def create_model(body: ModelCreateIn = ModelCreateIn()) -> ModelInfo:
    """Mint a new UID, create an empty RoomDoc, persist it, return {uid, name}."""
    uid = uuid4().hex
    doc = RoomDoc(uid=uid, name=body.name)
    _store[uid] = doc
    save_model(uid)
    return ModelInfo(uid=uid, name=doc.name)


# ── list available example templates ──────────────────────────────────────────

@router.get("/models/examples", response_model=list[ExampleInfo])
def list_example_templates() -> list[ExampleInfo]:
    """
    Return available example template names from examples.py.
    Returns [] (not 503) when the examples module is not yet installed, so the
    UI can gracefully show an empty list rather than crashing.
    """
    return [ExampleInfo(key=e["key"], name=e["name"]) for e in _list_examples()]


# ── create model from example ──────────────────────────────────────────────────

@router.post(
    "/models/from_example",
    status_code=status.HTTP_201_CREATED,
    response_model=ModelInfo,
)
def create_model_from_example(body: ModelFromExampleIn) -> ModelInfo:
    """
    Load an example template, copy it into a brand-new model UID, persist it,
    and return {uid, name}.

    The example originals are never mutated — each call produces an independent
    copy.  Returns HTTP 503 if the examples module has not been deployed yet.
    """
    example_dict = _load_example(body.example_key)
    if example_dict is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "The examples module is not yet available. "
                "Please try again once examples.py has been deployed."
            ),
        )

    # Mint a fresh UID; the caller may override the name.
    uid = uuid4().hex
    # Build a RoomDoc from the example dict (counters computed automatically
    # from existing IDs when not present in the dict).
    doc = roomdoc_from_dict(example_dict)
    doc.uid = uid
    if body.name is not None:
        doc.name = body.name
    elif not doc.name or doc.name == "Untitled":
        # Use example's own name if the caller didn't supply one.
        doc.name = example_dict.get("name", "Untitled")

    _store[uid] = doc
    save_model(uid)
    return ModelInfo(uid=uid, name=doc.name)


# ── rename model ───────────────────────────────────────────────────────────────

@router.patch("/models/{uid}", response_model=ModelInfo)
def rename_model(uid: str, body: ModelRenameIn) -> ModelInfo:
    """Change a model's human-readable name; the UID is never altered."""
    if uid not in _store:
        raise HTTPException(status_code=404, detail=f"Model '{uid}' not found.")
    doc = _store[uid]
    doc.name = body.name
    save_model(uid)
    return ModelInfo(uid=uid, name=doc.name)


# ── delete model ───────────────────────────────────────────────────────────────

@router.delete("/models/{uid}", status_code=status.HTTP_204_NO_CONTENT)
def delete_model(uid: str) -> None:
    """Remove the model from the session store and delete its JSON file."""
    if uid not in _store:
        raise HTTPException(status_code=404, detail=f"Model '{uid}' not found.")
    del _store[uid]
    delete_model_file(uid)
