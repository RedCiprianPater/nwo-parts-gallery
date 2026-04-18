"""
Part publish service.
Orchestrates: upload → hash → store → embed → persist.
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.orm import Part
from ..models.schemas import PartPublishMetadata, PublishResponse
from ..search.embeddings import build_embedding_text, get_embedding_provider
from ..storage.blob import (
    part_file_key,
    sha256_of_bytes,
    thumbnail_key,
    upload_file,
)
from ..storage.thumbnail import generate_thumbnail

_MAX_FILE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "100"))
_MAX_FILE_BYTES = _MAX_FILE_MB * 1024 * 1024


async def publish_part(
    db: AsyncSession,
    agent_id: str,
    file_bytes: bytes,
    file_format: str,
    metadata: PartPublishMetadata,
) -> PublishResponse:
    """
    Full publish pipeline:
    1. Validate file size
    2. Compute SHA-256
    3. Determine version number
    4. Upload file to blob store
    5. Generate + upload thumbnail
    6. Generate embedding for semantic search
    7. Persist Part record to database
    8. Mark previous latest version as non-latest

    Args:
        db: Async DB session.
        agent_id: Registered agent ID performing the publish.
        file_bytes: Raw file content.
        file_format: "stl" | "3mf" | "obj"
        metadata: PartPublishMetadata from the request.

    Returns:
        PublishResponse with the part ID and URLs.
    """
    # 1. Size check
    if len(file_bytes) > _MAX_FILE_BYTES:
        raise ValueError(f"File too large: {len(file_bytes) / 1e6:.1f} MB > {_MAX_FILE_MB} MB limit")

    # 2. Hash
    file_hash = sha256_of_bytes(file_bytes)
    slug = metadata.slug()

    # 3. Version number — find the latest existing version for this agent+slug
    existing_latest = (
        await db.execute(
            select(Part)
            .where(Part.agent_id == agent_id, Part.slug == slug, Part.is_latest == True)  # noqa: E712
        )
    ).scalar_one_or_none()

    version = (existing_latest.version + 1) if existing_latest else 1
    part_id = str(uuid.uuid4())

    # 4. Upload file
    fmt = file_format.lower().lstrip(".")
    fkey = part_file_key(agent_id, part_id, fmt)
    content_types = {"stl": "model/stl", "3mf": "model/3mf", "obj": "text/plain"}
    ct = content_types.get(fmt, "application/octet-stream")
    file_url = upload_file(file_bytes, fkey, content_type=ct)

    # 5. Thumbnail
    thumb_url: str | None = None
    tkey: str | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=f".{fmt}", delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = Path(tmp.name)
        png = generate_thumbnail(tmp_path)
        tmp_path.unlink(missing_ok=True)
        if png:
            tkey = thumbnail_key(agent_id, part_id)
            thumb_url = upload_file(png, tkey, content_type="image/png")
    except Exception:
        pass  # Thumbnail failure is non-fatal

    # 6. Embedding
    embedding: list[float] | None = None
    try:
        provider = get_embedding_provider()
        emb_text = build_embedding_text(
            name=metadata.name,
            description=metadata.description,
            category=metadata.category.value,
            body_zone=metadata.body_zone.value if metadata.body_zone else None,
            tags=metadata.tags,
            material_hints=metadata.material_hints,
            connector_standard=metadata.connector_standard,
        )
        vec = await provider.embed(emb_text)
        embedding = vec if vec else None
    except Exception:
        pass  # Embedding failure is non-fatal

    # 7. Extract mesh stats if trimesh available
    mesh_vertices = mesh_faces = None
    bbox: list[float] | None = None
    try:
        import trimesh
        with tempfile.NamedTemporaryFile(suffix=f".{fmt}", delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = Path(tmp.name)
        mesh = trimesh.load(str(tmp_path), force="mesh")
        tmp_path.unlink(missing_ok=True)
        mesh_vertices = len(mesh.vertices)
        mesh_faces = len(mesh.faces)
        bbox = mesh.bounding_box.extents.tolist()
    except Exception:
        pass

    # 8. Persist
    ps = metadata.print_settings
    part = Part(
        id=part_id,
        agent_id=agent_id,
        name=metadata.name,
        slug=slug,
        version=version,
        is_latest=True,
        is_deprecated=False,
        category=metadata.category.value,
        body_zone=metadata.body_zone.value if metadata.body_zone else None,
        description=metadata.description,
        tags=metadata.tags,
        file_key=fkey,
        file_format=fmt,
        file_size_bytes=len(file_bytes),
        file_hash_sha256=file_hash,
        thumbnail_key=tkey,
        material_hints=metadata.material_hints,
        infill_pct=ps.infill_pct,
        layer_height_mm=ps.layer_height_mm,
        supports_required=ps.supports_required,
        connector_standard=metadata.connector_standard or ps.connector_standard,
        tolerance_class=ps.tolerance_class.value if ps.tolerance_class else None,
        validation_passed=metadata.validation_passed,
        validation_report=metadata.validation_report,
        mesh_vertices=mesh_vertices,
        mesh_faces=mesh_faces,
        bounding_box_mm=bbox,
        license=metadata.license.value,
        generator=metadata.generator,
        llm_provider=metadata.llm_provider,
        llm_model=metadata.llm_model,
        source_prompt=metadata.source_prompt,
        agent_signature=metadata.agent_signature,
        embedding=embedding,
    )
    db.add(part)

    # Mark previous latest as non-latest
    if existing_latest:
        await db.execute(
            update(Part)
            .where(Part.id == existing_latest.id)
            .values(is_latest=False)
        )

    await db.flush()

    return PublishResponse(
        part_id=part_id,
        name=metadata.name,
        version=version,
        file_url=file_url,
        thumbnail_url=thumb_url,
        message=f"Published '{metadata.name}' v{version} successfully.",
    )
