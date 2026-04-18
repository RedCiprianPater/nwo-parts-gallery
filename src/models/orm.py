"""
SQLAlchemy ORM models for the NWO Parts Gallery.

Tables:
  agents      — registered robot/agent identities
  parts       — published part records (one row per version)
  part_tags   — many-to-many tags on parts
  downloads   — download event log (analytics)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


# ── Agent ──────────────────────────────────────────────────────────────────────

class Agent(Base):
    """
    A registered agent (robot or human publisher).
    Agents sign their publishes with their ed25519 public key.
    """
    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    public_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    key_algorithm: Mapped[str] = mapped_column(String(16), default="ed25519")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)

    parts: Mapped[list["Part"]] = relationship("Part", back_populates="agent")

    def __repr__(self) -> str:
        return f"<Agent id={self.id} name={self.name}>"


# ── Part ───────────────────────────────────────────────────────────────────────

class Part(Base):
    """
    A published robot part.
    Each publish of the same logical part creates a new row with incremented version.
    The (agent_id, slug, version) triple is unique.
    """
    __tablename__ = "parts"
    __table_args__ = (
        UniqueConstraint("agent_id", "slug", "version", name="uq_part_agent_slug_version"),
        Index("ix_parts_category", "category"),
        Index("ix_parts_body_zone", "body_zone"),
        Index("ix_parts_created_at", "created_at"),
        Index("ix_parts_agent_id", "agent_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    agent_id: Mapped[str] = mapped_column(String(36), ForeignKey("agents.id"), nullable=False)

    # Identity
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    slug: Mapped[str] = mapped_column(String(256), nullable=False)   # url-safe name
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_latest: Mapped[bool] = mapped_column(Boolean, default=True)
    is_deprecated: Mapped[bool] = mapped_column(Boolean, default=False)

    # Classification
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    # Categories: joint | frame | gripper | wheel | sensor_mount | structural | end_effector | other
    body_zone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Body zones: arm | leg | torso | head | base | universal

    # Description
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)

    # File info
    file_key: Mapped[str] = mapped_column(String(512), nullable=False)  # S3 object key
    file_format: Mapped[str] = mapped_column(String(16), nullable=False)  # stl | 3mf | obj
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    file_hash_sha256: Mapped[str] = mapped_column(String(64), nullable=False)

    # Thumbnail
    thumbnail_key: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # Print settings
    material_hints: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    # e.g. ["PLA", "PETG"]
    infill_pct: Mapped[int | None] = mapped_column(Integer, nullable=True)
    layer_height_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    supports_required: Mapped[bool] = mapped_column(Boolean, default=False)
    connector_standard: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # e.g. M2 | M3 | M4 | M5 | imperial
    tolerance_class: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # e.g. tight | standard | loose

    # Validation results from Layer 1
    validation_passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    validation_report: Mapped[dict] = mapped_column(JSONB, default=dict)

    # Mesh stats
    mesh_vertices: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mesh_faces: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bounding_box_mm: Mapped[list | None] = mapped_column(ARRAY(Float), nullable=True)
    # [x, y, z] extents

    # Licensing
    license: Mapped[str] = mapped_column(String(32), default="CC0")
    # CC0 | CC-BY | MIT | proprietary

    # Generation provenance
    generator: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # e.g. "NWO Design Engine v0.1.0"
    llm_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    llm_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_script: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Stats
    download_count: Mapped[int] = mapped_column(Integer, default=0)
    view_count: Mapped[int] = mapped_column(Integer, default=0)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    # Signature
    agent_signature: Mapped[str | None] = mapped_column(Text, nullable=True)
    # hex-encoded ed25519 signature of (file_hash + name + version)

    # Vector embedding for semantic search (stored in pgvector)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)

    agent: Mapped["Agent"] = relationship("Agent", back_populates="parts")
    download_events: Mapped[list["DownloadEvent"]] = relationship("DownloadEvent", back_populates="part")

    def __repr__(self) -> str:
        return f"<Part id={self.id} name={self.name} v{self.version}>"


# ── DownloadEvent ──────────────────────────────────────────────────────────────

class DownloadEvent(Base):
    """Analytics: one row per download."""
    __tablename__ = "download_events"
    __table_args__ = (
        Index("ix_downloads_part_id", "part_id"),
        Index("ix_downloads_created_at", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    part_id: Mapped[str] = mapped_column(String(36), ForeignKey("parts.id"), nullable=False)
    downloader_agent_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    ip_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)  # hashed for privacy
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    part: Mapped["Part"] = relationship("Part", back_populates="download_events")
