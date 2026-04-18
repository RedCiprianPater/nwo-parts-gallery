"""
Search service.
Combines PostgreSQL full-text search with pgvector cosine similarity.

Strategy:
  1. If query provided + semantic=True + embeddings configured:
       Run vector similarity search, filtered by any facets.
  2. If query provided + semantic=False (or no embedding provider):
       PostgreSQL full-text search on name + description + tags.
  3. If no query:
       Filter-only query (faceted browse), ordered by sort_by.

Results are always deduplicated and paginated.
"""

from __future__ import annotations

import os

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.orm import Part
from ..models.schemas import SearchQuery, SearchResponse, PartSummary
from ..storage.blob import public_url, thumbnail_key
from .embeddings import (
    EMBEDDING_PROVIDER,
    build_embedding_text,
    get_embedding_provider,
)

_EMBEDDING_DIMS = int(os.getenv("EMBEDDING_DIMENSIONS", "1536"))


async def search_parts(db: AsyncSession, query: SearchQuery) -> SearchResponse:
    """
    Execute a search query and return paginated results.
    """
    # Build base filter conditions
    filters = [
        Part.is_latest == True,        # noqa: E712
        Part.is_deprecated == False,   # noqa: E712
    ]

    if query.category:
        filters.append(Part.category == query.category.value)
    if query.body_zone:
        filters.append(Part.body_zone == query.body_zone.value)
    if query.license:
        filters.append(Part.license == query.license.value)
    if query.agent_id:
        filters.append(Part.agent_id == query.agent_id)
    if query.supports_required is not None:
        filters.append(Part.supports_required == query.supports_required)
    if query.connector_standard:
        filters.append(Part.connector_standard == query.connector_standard)
    if query.material:
        filters.append(Part.material_hints.any(query.material))
    if query.tags:
        for tag in query.tags:
            filters.append(Part.tags.any(tag))

    # Determine search strategy
    use_semantic = bool(
        query.q
        and query.semantic
        and EMBEDDING_PROVIDER != "none"
    )

    if use_semantic:
        results, total = await _semantic_search(db, query, filters)
    elif query.q:
        results, total = await _fulltext_search(db, query, filters)
    else:
        results, total = await _filter_search(db, query, filters)

    summaries = [_to_summary(p) for p in results]

    return SearchResponse(
        total=total,
        limit=query.limit,
        offset=query.offset,
        query=query.q,
        results=summaries,
    )


async def _semantic_search(
    db: AsyncSession, query: SearchQuery, filters: list
) -> tuple[list[Part], int]:
    """Vector cosine similarity search via pgvector."""
    provider = get_embedding_provider()
    query_vec = await provider.embed(query.q)

    if not query_vec:
        return await _fulltext_search(db, query, filters)

    vec_str = f"[{','.join(str(v) for v in query_vec)}]"

    # cosine distance: 1 - (a · b / |a||b|)
    distance_expr = text(f"embedding <=> '{vec_str}'::vector")

    stmt = (
        select(Part)
        .where(and_(*filters), Part.embedding.is_not(None))
        .order_by(distance_expr)
        .limit(query.limit)
        .offset(query.offset)
    )

    count_stmt = (
        select(func.count())
        .select_from(Part)
        .where(and_(*filters), Part.embedding.is_not(None))
    )

    results = (await db.execute(stmt)).scalars().all()
    total = (await db.execute(count_stmt)).scalar() or 0

    return list(results), int(total)


async def _fulltext_search(
    db: AsyncSession, query: SearchQuery, filters: list
) -> tuple[list[Part], int]:
    """PostgreSQL full-text search on name + description + tags."""
    q = query.q.strip()

    # tsvector on name + description
    ts_query = func.plainto_tsquery("english", q)
    ts_vector = func.to_tsvector(
        "english",
        func.coalesce(Part.name, "") + " " + func.coalesce(Part.description, ""),
    )
    ts_filter = ts_vector.op("@@")(ts_query)

    # Also match tags (simple ILIKE fallback)
    name_filter = Part.name.ilike(f"%{q}%")
    tag_filter = Part.tags.any(q.lower())

    text_filters = or_(ts_filter, name_filter, tag_filter)

    order = _sort_expr(query.sort_by)

    stmt = (
        select(Part)
        .where(and_(*filters, text_filters))
        .order_by(order)
        .limit(query.limit)
        .offset(query.offset)
    )
    count_stmt = (
        select(func.count())
        .select_from(Part)
        .where(and_(*filters, text_filters))
    )

    results = (await db.execute(stmt)).scalars().all()
    total = (await db.execute(count_stmt)).scalar() or 0
    return list(results), int(total)


async def _filter_search(
    db: AsyncSession, query: SearchQuery, filters: list
) -> tuple[list[Part], int]:
    """Faceted browse without a text query."""
    order = _sort_expr(query.sort_by)

    stmt = (
        select(Part)
        .where(and_(*filters))
        .order_by(order)
        .limit(query.limit)
        .offset(query.offset)
    )
    count_stmt = select(func.count()).select_from(Part).where(and_(*filters))

    results = (await db.execute(stmt)).scalars().all()
    total = (await db.execute(count_stmt)).scalar() or 0
    return list(results), int(total)


def _sort_expr(sort_by: str):
    from sqlalchemy import desc
    if sort_by == "downloads":
        return desc(Part.download_count)
    if sort_by == "name":
        return Part.name
    return desc(Part.created_at)


def _to_summary(part: Part) -> PartSummary:
    thumb_url = None
    if part.thumbnail_key:
        thumb_url = public_url(part.thumbnail_key)

    return PartSummary(
        id=part.id,
        name=part.name,
        slug=part.slug,
        version=part.version,
        category=part.category,
        body_zone=part.body_zone,
        description=part.description,
        tags=part.tags or [],
        material_hints=part.material_hints or [],
        file_format=part.file_format,
        file_size_bytes=part.file_size_bytes,
        license=part.license,
        download_count=part.download_count,
        validation_passed=part.validation_passed,
        thumbnail_url=thumb_url,
        agent_id=part.agent_id,
        created_at=part.created_at,
    )
