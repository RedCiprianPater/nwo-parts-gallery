"""
Gallery HTML routes — server-side rendered using Jinja2.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.database import get_session
from ..models.orm import Agent, DownloadEvent, Part
from ..models.schemas import BodyZone, License, PartCategory, SearchQuery
from ..search.service import search_parts, _to_summary

_TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

_API_BASE = os.getenv("GALLERY_BASE_URL", "http://localhost:8001")

gallery_router = APIRouter()
DB = Annotated[AsyncSession, Depends(get_session)]


@gallery_router.get("/gallery", response_class=HTMLResponse, tags=["Gallery"])
async def gallery_index(
    request: Request,
    db: DB,
    q: str | None = Query(default=None),
    category: str | None = Query(default=None),
    body_zone: str | None = Query(default=None),
    material: str | None = Query(default=None),
    connector_standard: str | None = Query(default=None),
    license: str | None = Query(default=None),
    agent_id: str | None = Query(default=None),
    sort_by: str = Query(default="created_at"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=24, ge=1, le=100),
):
    """Browse the parts gallery (HTML)."""

    # Build search query
    sq = SearchQuery(
        q=q,
        category=PartCategory(category) if category else None,
        body_zone=BodyZone(body_zone) if body_zone else None,
        material=material,
        connector_standard=connector_standard,
        license=License(license) if license else None,
        agent_id=agent_id,
        limit=limit,
        offset=offset,
        sort_by=sort_by,
        semantic=True,
    )

    results = await search_parts(db, sq)

    # Global stats
    total_parts = (await db.execute(select(func.count()).select_from(Part))).scalar() or 0
    total_agents = (await db.execute(select(func.count()).select_from(Agent))).scalar() or 0
    total_downloads = (
        await db.execute(select(func.sum(Part.download_count)))
    ).scalar() or 0

    # Build base_query string for pagination links (excludes offset)
    params = dict(request.query_params)
    params.pop("offset", None)
    base_query = "&".join(f"{k}={v}" for k, v in params.items())

    return templates.TemplateResponse(
        "gallery.html",
        {
            "request": request,
            "parts": results.results,
            "total": results.total,
            "limit": limit,
            "offset": offset,
            "query": sq,
            "total_parts": total_parts,
            "total_agents": total_agents,
            "total_downloads": total_downloads,
            "categories": [c.value for c in PartCategory],
            "body_zones": [z.value for z in BodyZone],
            "base_query": base_query,
        },
    )


@gallery_router.get("/gallery/{part_id}", response_class=HTMLResponse, tags=["Gallery"])
async def part_detail(request: Request, part_id: str, db: DB):
    """Part detail page (HTML)."""
    from fastapi import HTTPException

    part = (await db.execute(
        select(Part).where(Part.id == part_id)
    )).scalar_one_or_none()

    if not part:
        raise HTTPException(status_code=404, detail="Part not found")

    # Load agent
    agent = (await db.execute(
        select(Agent).where(Agent.id == part.agent_id)
    )).scalar_one_or_none()

    # Load all versions
    versions = (await db.execute(
        select(Part)
        .where(Part.agent_id == part.agent_id, Part.slug == part.slug)
        .order_by(Part.version.desc())
    )).scalars().all()

    part_summary = _to_summary(part)

    return templates.TemplateResponse(
        "part_detail.html",
        {
            "request": request,
            "part": part,
            "agent": agent,
            "versions": [_to_summary(v) for v in versions],
            "api_base": _API_BASE,
        },
    )
