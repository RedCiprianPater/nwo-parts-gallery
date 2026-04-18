"""
Embedding provider for semantic search.
Converts part names + descriptions + tags into dense vectors stored in pgvector.

Supported backends:
  - openai   (text-embedding-3-small, 1536 dims)
  - ollama   (nomic-embed-text, 768 dims)
  - none     (disables semantic search, falls back to full-text only)
"""

from __future__ import annotations

import os
from typing import Protocol


EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "openai")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
EMBEDDING_DIMS = int(os.getenv("EMBEDDING_DIMENSIONS", "1536"))
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_EMBEDDING_MODEL = os.getenv("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text")


class EmbeddingProvider(Protocol):
    async def embed(self, text: str) -> list[float]: ...
    async def embed_batch(self, texts: list[str]) -> list[list[float]]: ...


class OpenAIEmbeddingProvider:
    def __init__(self) -> None:
        from openai import AsyncOpenAI
        self._client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self._model = EMBEDDING_MODEL

    async def embed(self, text: str) -> list[float]:
        resp = await self._client.embeddings.create(input=text, model=self._model)
        return resp.data[0].embedding

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        resp = await self._client.embeddings.create(input=texts, model=self._model)
        return [d.embedding for d in sorted(resp.data, key=lambda x: x.index)]


class OllamaEmbeddingProvider:
    def __init__(self) -> None:
        import httpx
        self._client = httpx.AsyncClient(base_url=OLLAMA_BASE_URL, timeout=60.0)
        self._model = OLLAMA_EMBEDDING_MODEL

    async def embed(self, text: str) -> list[float]:
        resp = await self._client.post("/api/embeddings", json={"model": self._model, "prompt": text})
        resp.raise_for_status()
        return resp.json()["embedding"]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        results = []
        for text in texts:
            results.append(await self.embed(text))
        return results


class NullEmbeddingProvider:
    """No-op provider when semantic search is disabled."""
    async def embed(self, text: str) -> list[float]:
        return []

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [[] for _ in texts]


def get_embedding_provider() -> EmbeddingProvider:
    if EMBEDDING_PROVIDER == "openai":
        return OpenAIEmbeddingProvider()
    if EMBEDDING_PROVIDER == "ollama":
        return OllamaEmbeddingProvider()
    return NullEmbeddingProvider()


def build_embedding_text(
    name: str,
    description: str | None,
    category: str,
    body_zone: str | None,
    tags: list[str],
    material_hints: list[str],
    connector_standard: str | None,
) -> str:
    """
    Construct the text string that will be embedded for a part.
    This string is what agents search against semantically.
    """
    parts = [
        f"Part: {name}",
        f"Category: {category}",
    ]
    if body_zone:
        parts.append(f"Body zone: {body_zone}")
    if description:
        parts.append(f"Description: {description}")
    if tags:
        parts.append(f"Tags: {', '.join(tags)}")
    if material_hints:
        parts.append(f"Materials: {', '.join(material_hints)}")
    if connector_standard:
        parts.append(f"Connector: {connector_standard}")
    return ". ".join(parts)
