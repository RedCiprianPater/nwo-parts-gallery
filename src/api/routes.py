"""
FastAPI routes for the NWO Parts Gallery.
"""

from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.database import get_session
from ..models.orm import Agent, DownloadEvent, Part
from ..models.schemas import (
    AgentRegisterRequest,
    AgentResponse,
    BodyZone,
    License,
    PartCategory,
    PartDetail,
    PublishResponse,
    SearchQuery,
    SearchResponse,
)
from ..search.service import search_parts, _to_summary
from ..storage.blob import presigned_url, public_url
from .identity import get_agent, register_agent
from .publish import publish_part

router = APIRouter()

DB = Annotated[AsyncSession, Depends(get_session)]


# ── /agents ────────────────────────────────────────────────────────────────────

@router.post("/agents/register", response_model=AgentResponse, tags=["Agents"])
async def register(req: AgentRegisterRequest, db: DB):
    """Register a new agent identity with its public key."""
    agent = await register_agent(db, req)
    count = (await db.execute(
        select(func.count()).select_from(Part).where(Part.agent_id == agent.id)
    )).scalar() or 0
    return AgentResponse(
        id=agent.id,
        name=agent.name,
        description=agent.description,
        is_active=agent.is_active,
        created_at=agent.created_at,
        part_count=int(count),
    )


@router.get("/agents/{agent_id}", response_model=AgentResponse, tags=["Agents"])
async def get_agent_profile(agent_id: str, db: DB):
    """Get agent profile and part count."""
    agent = await get_agent(db, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    count = (await db.execute(
        select(func.count()).select_from(Part).where(Part.agent_id == agent_id)
    )).scalar() or 0
    return AgentResponse(
        id=agent.id,
        name=agent.name,
        description=agent.description,
        is_active=agent.is_active,
        created_at=agent.created_at,
        part_count=int(count),
    )


# ── /parts/publish ────────────────────────────────────────────────────────────

@router.post("/parts/publish", response_model=PublishResponse, tags=["Parts"])
async def publish(
    db: DB,
    file: UploadFile = File(..., description="STL, 3MF, or OBJ file"),
    metadata: str = Form(..., description="JSON-encoded PartPublishMetadata"),
    x_agent_id: str | None = Header(default=None, alias="X-Agent-ID"),
):
    """
    Publish a new part or version.
    Requires a registered agent ID in the X-Agent-ID header.
    Metadata must be a JSON-encoded PartPublishMetadata object passed as a form field.
    """
    if not x_agent_id:
        raise HTTPException(status_code=401, detail="X-Agent-ID header required")

    agent = await get_agent(db, x_agent_id)
    if not agent or not agent.is_active:
        raise HTTPException(status_code=403, detail="Unknown or inactive agent")

    # Parse metadata
    try:
        from ..models.schemas import PartPublishMetadata
        meta = PartPublishMetadata.model_validate_json(metadata)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Invalid metadata: {e}")

    # Read file
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=422, detail="Empty file")

    # Determine format from filename
    filename = file.filename or "part.stl"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "stl"
    if ext not in ("stl", "3mf", "obj"):
        raise HTTPException(status_code=422, detail=f"Unsupported file format: .{ext}")

    try:
        result = await publish_part(db, x_agent_id, file_bytes, ext, meta)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return result


# ── /parts/search ─────────────────────────────────────────────────────────────

@router.get("/parts/search", response_model=SearchResponse, tags=["Parts"])
async def search(
    db: DB,
    q: str | None = Query(default=None),
    category: PartCategory | None = Query(default=None),
    body_zone: BodyZone | None = Query(default=None),
    material: str | None = Query(default=None),
    connector_standard: str | None = Query(default=None),
    license: License | None = Query(default=None),
    supports_required: bool | None = Query(default=None),
    agent_id: str | None = Query(default=None),
    tags: list[str] = Query(default=[]),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    sort_by: str = Query(default="created_at"),
    semantic: bool = Query(default=True),
):
    """
    Search the parts gallery.
    Combines full-text and semantic (vector) search with faceted filtering.
    """
    query = SearchQuery(
        q=q,
        category=category,
        body_zone=body_zone,
        material=material,
        connector_standard=connector_standard,
        license=license,
        supports_required=supports_required,
        agent_id=agent_id,
        tags=tags,
        limit=limit,
        offset=offset,
        sort_by=sort_by,
        semantic=semantic,
    )
    return await search_parts(db, query)


# ── /parts/{id} ───────────────────────────────────────────────────────────────

@router.get("/parts/{part_id}", response_model=PartDetail, tags=["Parts"])
async def get_part(part_id: str, db: DB):
    """Get full part details including provenance and print settings."""
    part = (await db.execute(
        select(Part).where(Part.id == part_id)
    )).scalar_one_or_none()

    if not part:
        raise HTTPException(status_code=404, detail="Part not found")

    agent = await get_agent(db, part.agent_id)
    agent_resp = AgentResponse(
        id=agent.id, name=agent.name, description=agent.description,
        is_active=agent.is_active, created_at=agent.created_at,
    ) if agent else None

    summary = _to_summary(part)
    return PartDetail(
        **summary.model_dump(),
        infill_pct=part.infill_pct,
        layer_height_mm=part.layer_height_mm,
        supports_required=part.supports_required,
        connector_standard=part.connector_standard,
        tolerance_class=part.tolerance_class,
        mesh_vertices=part.mesh_vertices,
        mesh_faces=part.mesh_faces,
        bounding_box_mm=part.bounding_box_mm,
        generator=part.generator,
        llm_provider=part.llm_provider,
        llm_model=part.llm_model,
        source_prompt=part.source_prompt,
        validation_report=part.validation_report or {},
        file_url=public_url(part.file_key),
        agent=agent_resp,
    )


@router.get("/parts/{part_id}/file", tags=["Parts"])
async def download_part_file(part_id: str, db: DB):
    """Download the mesh file for a part. Increments download counter."""
    part = (await db.execute(
        select(Part).where(Part.id == part_id)
    )).scalar_one_or_none()

    if not part:
        raise HTTPException(status_code=404, detail="Part not found")

    # Increment download count
    await db.execute(
        update(Part).where(Part.id == part_id).values(download_count=Part.download_count + 1)
    )
    db.add(DownloadEvent(part_id=part_id))

    url = presigned_url(part.file_key)
    return RedirectResponse(url=url, status_code=302)


@router.get("/parts/{part_id}/versions", tags=["Parts"])
async def list_versions(part_id: str, db: DB):
    """List all published versions of a part (by slug + agent)."""
    part = (await db.execute(
        select(Part).where(Part.id == part_id)
    )).scalar_one_or_none()

    if not part:
        raise HTTPException(status_code=404, detail="Part not found")

    versions = (await db.execute(
        select(Part)
        .where(Part.agent_id == part.agent_id, Part.slug == part.slug)
        .order_by(Part.version.desc())
    )).scalars().all()

    return [_to_summary(v) for v in versions]


@router.delete("/parts/{part_id}", tags=["Parts"])
async def deprecate_part(
    part_id: str,
    db: DB,
    x_agent_id: str | None = Header(default=None, alias="X-Agent-ID"),
):
    """Deprecate a part (agent must be the original publisher)."""
    if not x_agent_id:
        raise HTTPException(status_code=401, detail="X-Agent-ID header required")

    part = (await db.execute(
        select(Part).where(Part.id == part_id)
    )).scalar_one_or_none()

    if not part:
        raise HTTPException(status_code=404, detail="Part not found")

    if part.agent_id != x_agent_id:
        raise HTTPException(status_code=403, detail="You can only deprecate your own parts")

    await db.execute(
        update(Part).where(Part.id == part_id).values(is_deprecated=True)
    )
    return {"message": f"Part {part_id} deprecated"}
