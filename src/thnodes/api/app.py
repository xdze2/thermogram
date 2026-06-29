"""
FastAPI application entry point.

Creates the "default" model at startup and mounts all route modules.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from .models import RoomDoc
from .store import _store
from .routes import registry, document, assembly, simulate, identifiability, topology


@asynccontextmanager
async def _lifespan(app: FastAPI):
    _store["default"] = RoomDoc()
    yield


app = FastAPI(title="thnodes API", version="0.1.0", lifespan=_lifespan)

PREFIX = "/api"

app.include_router(registry.router, prefix=PREFIX)
app.include_router(document.router, prefix=PREFIX)
app.include_router(assembly.router, prefix=PREFIX)
app.include_router(simulate.router, prefix=PREFIX)
app.include_router(identifiability.router, prefix=PREFIX)
app.include_router(topology.router, prefix=PREFIX)
