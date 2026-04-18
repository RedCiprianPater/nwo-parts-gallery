"""NWO Parts Gallery — FastAPI application."""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..gallery.router import gallery_router
from ..models.database import create_tables
from ..storage.blob import ensure_bucket
from .routes import router

app = FastAPI(
    title="NWO Parts Gallery",
    description="Layer 2 of the NWO Robotics platform — searchable robot parts gallery and agent file store.",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
app.include_router(gallery_router)


@app.get("/", tags=["System"])
async def root():
    return {"service": "nwo-parts-gallery", "gallery": "/gallery", "docs": "/docs"}


@app.on_event("startup")
async def startup():
    """Initialise database tables and blob bucket on startup."""
    try:
        await create_tables()
    except Exception as e:
        print(f"[WARN] DB init: {e}")
    try:
        ensure_bucket()
    except Exception as e:
        print(f"[WARN] Blob bucket init: {e}")


@app.get("/health", tags=["System"])
async def health():
    return {"status": "ok", "service": "nwo-parts-gallery"}
