"""
Pydantic schemas for the Parts Gallery API.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator
import re


# ── Enums ──────────────────────────────────────────────────────────────────────

class PartCategory(str, Enum):
    joint = "joint"
    frame = "frame"
    gripper = "gripper"
    wheel = "wheel"
    sensor_mount = "sensor_mount"
    structural = "structural"
    end_effector = "end_effector"
    other = "other"


class BodyZone(str, Enum):
    arm = "arm"
    leg = "leg"
    torso = "torso"
    head = "head"
    base = "base"
    universal = "universal"


class FileFormat(str, Enum):
    stl = "stl"
    three_mf = "3mf"
    obj = "obj"


class License(str, Enum):
    cc0 = "CC0"
    cc_by = "CC-BY"
    mit = "MIT"
    proprietary = "proprietary"


class ToleranceClass(str, Enum):
    tight = "tight"
    standard = "standard"
    loose = "loose"


# ── Print settings ─────────────────────────────────────────────────────────────

class PrintSettings(BaseModel):
    infill_pct: int | None = Field(default=None, ge=0, le=100)
    layer_height_mm: float | None = Field(default=None, ge=0.05, le=1.0)
    supports_required: bool = False
    connector_standard: str | None = None
    tolerance_class: ToleranceClass | None = None


# ── Agent schemas ──────────────────────────────────────────────────────────────

class AgentRegisterRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=128)
    description: str | None = None
    public_key: str = Field(..., description="PEM or base64-encoded ed25519 public key")
    key_algorithm: str = Field(default="ed25519")
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentResponse(BaseModel):
    id: str
    name: str
    description: str | None
    is_active: bool
    created_at: datetime
    part_count: int = 0

    model_config = {"from_attributes": True}


# ── Part publish ───────────────────────────────────────────────────────────────

class PartPublishMetadata(BaseModel):
    """Metadata submitted alongside the file when publishing a part."""

    name: str = Field(..., min_length=3, max_length=256)
    category: PartCategory
    body_zone: BodyZone | None = None
    description: str | None = Field(default=None, max_length=4096)
    tags: list[str] = Field(default_factory=list, max_length=20)
    material_hints: list[str] = Field(default_factory=list)
    print_settings: PrintSettings = Field(default_factory=PrintSettings)
    license: License = License.cc0
    connector_standard: str | None = None

    # Provenance (filled by the design engine automatically)
    generator: str | None = None
    llm_provider: str | None = None
    llm_model: str | None = None
    source_prompt: str | None = None

    # Agent signature over (file_sha256 + name + str(version))
    agent_signature: str | None = None

    # Validation report from Layer 1
    validation_report: dict[str, Any] = Field(default_factory=dict)
    validation_passed: bool | None = None

    @field_validator("tags")
    @classmethod
    def clean_tags(cls, v: list[str]) -> list[str]:
        return [re.sub(r"[^a-z0-9\-_]", "", t.lower().strip())[:32] for t in v if t.strip()]

    def slug(self) -> str:
        """Generate a URL-safe slug from the name."""
        s = re.sub(r"[^a-z0-9]+", "-", self.name.lower()).strip("-")
        return s[:128]


# ── Part response ──────────────────────────────────────────────────────────────

class PartSummary(BaseModel):
    """Compact part representation for search results and gallery listings."""
    id: str
    name: str
    slug: str
    version: int
    category: str
    body_zone: str | None
    description: str | None
    tags: list[str]
    material_hints: list[str]
    file_format: str
    file_size_bytes: int
    license: str
    download_count: int
    validation_passed: bool | None
    thumbnail_url: str | None
    agent_id: str
    created_at: datetime

    model_config = {"from_attributes": True}


class PartDetail(PartSummary):
    """Full part record including print settings and provenance."""
    infill_pct: int | None
    layer_height_mm: float | None
    supports_required: bool
    connector_standard: str | None
    tolerance_class: str | None
    mesh_vertices: int | None
    mesh_faces: int | None
    bounding_box_mm: list[float] | None
    generator: str | None
    llm_provider: str | None
    llm_model: str | None
    source_prompt: str | None
    validation_report: dict[str, Any]
    file_url: str
    agent: AgentResponse

    model_config = {"from_attributes": True}


class PublishResponse(BaseModel):
    part_id: str
    name: str
    version: int
    file_url: str
    thumbnail_url: str | None
    message: str


# ── Search ─────────────────────────────────────────────────────────────────────

class SearchQuery(BaseModel):
    q: str | None = Field(default=None, description="Full-text or semantic search query")
    category: PartCategory | None = None
    body_zone: BodyZone | None = None
    material: str | None = None
    connector_standard: str | None = None
    license: License | None = None
    supports_required: bool | None = None
    agent_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)
    sort_by: str = Field(default="created_at")  # created_at | downloads | name | similarity
    semantic: bool = Field(default=True, description="Use vector similarity if a query is provided")


class SearchResponse(BaseModel):
    total: int
    limit: int
    offset: int
    query: str | None
    results: list[PartSummary]
