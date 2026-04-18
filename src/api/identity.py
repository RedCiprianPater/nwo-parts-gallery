"""
Agent identity management and signature verification.

Agents sign their publishes with an ed25519 private key.
The gallery stores only the public key and verifies signatures on ingest.
This gives every part a verifiable on-chain-style provenance without a blockchain.

Signature scheme:
  message = SHA256(file_bytes) + ":" + part_name + ":" + str(version)
  signature = ed25519_sign(private_key, message.encode())
  published as: hex(signature)
"""

from __future__ import annotations

import binascii
import hashlib
import os

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.orm import Agent
from ..models.schemas import AgentRegisterRequest


async def register_agent(db: AsyncSession, req: AgentRegisterRequest) -> Agent:
    """Register a new agent, or return the existing one if the public key matches."""
    existing = (
        await db.execute(select(Agent).where(Agent.public_key == req.public_key))
    ).scalar_one_or_none()

    if existing:
        return existing

    agent = Agent(
        name=req.name,
        description=req.description,
        public_key=req.public_key,
        key_algorithm=req.key_algorithm,
        metadata_=req.metadata,
    )
    db.add(agent)
    await db.flush()
    return agent


async def get_agent(db: AsyncSession, agent_id: str) -> Agent | None:
    return (
        await db.execute(select(Agent).where(Agent.id == agent_id))
    ).scalar_one_or_none()


def verify_signature(
    public_key_hex: str,
    file_hash_sha256: str,
    part_name: str,
    version: int,
    signature_hex: str,
) -> bool:
    """
    Verify an ed25519 signature over the part's identity payload.

    Returns True if valid, False otherwise (never raises).
    """
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from cryptography.hazmat.primitives.serialization import (
            Encoding,
            PublicFormat,
            load_pem_public_key,
            load_der_public_key,
        )
        from cryptography.exceptions import InvalidSignature

        message = f"{file_hash_sha256}:{part_name}:{version}".encode()
        signature = binascii.unhexlify(signature_hex)

        # Try to load as PEM first, then raw bytes
        try:
            if public_key_hex.startswith("-----"):
                pub_key = load_pem_public_key(public_key_hex.encode())
            else:
                raw = binascii.unhexlify(public_key_hex)
                pub_key = Ed25519PublicKey.from_public_bytes(raw)
        except Exception:
            return False

        pub_key.verify(signature, message)
        return True
    except Exception:
        return False


def build_message(file_hash_sha256: str, part_name: str, version: int) -> str:
    """Build the canonical signing message for a part publish."""
    return f"{file_hash_sha256}:{part_name}:{version}"


def get_agent_id_from_request(
    agent_id_header: str | None,
    agent_key_header: str | None,
) -> tuple[str | None, str | None]:
    """Extract agent credentials from request headers."""
    return agent_id_header, agent_key_header
