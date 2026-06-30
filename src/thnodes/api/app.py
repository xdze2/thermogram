"""
FastAPI application entry point.

On startup, scans ``user_data/`` for persisted models.  When no files are
found (first run), seeds one model with uid "default" so that existing tests
and the current frontend continue to work unchanged.

Mounts all route modules including the new model-management router.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from .models import RoomDoc
from .store import _store, load_all_models, save_model
from .routes import registry, document, assembly, simulate, identifiability, topology
from .routes import models as models_router
from .routes.influx import influx_router, model_router as influx_model_router


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # Only load from disk when the store is empty.  Tests pre-populate _store
    # via fixtures before the TestClient lifespan fires; skipping the load
    # prevents persisted files from overwriting those injected stubs.
    if not _store:
        load_all_models()

        # Backward-compat: if user_data/ was empty (first run), seed one model
        # with uid "default" so existing tests and the frontend can hit
        # /api/models/default/... without any setup step.
        if not _store:
            default_doc = RoomDoc(uid="default", name="Default")
            _store["default"] = default_doc
            save_model("default")

    yield


app = FastAPI(title="thnodes API", version="0.1.0", lifespan=_lifespan)

PREFIX = "/api"

# Model-management router must be mounted BEFORE the document/assembly routers
# so that the fixed paths (/models/examples, /models/from_example) are matched
# before the parameterised prefix /models/{model_id} swallows them.
app.include_router(models_router.router, prefix=PREFIX)
app.include_router(registry.router, prefix=PREFIX)
app.include_router(document.router, prefix=PREFIX)
app.include_router(assembly.router, prefix=PREFIX)
app.include_router(simulate.router, prefix=PREFIX)
app.include_router(identifiability.router, prefix=PREFIX)
app.include_router(topology.router, prefix=PREFIX)
app.include_router(influx_router, prefix=PREFIX)
app.include_router(influx_model_router, prefix=PREFIX)
