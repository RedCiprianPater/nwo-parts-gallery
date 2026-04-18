"""
S3-compatible blob storage client.
Works with AWS S3, MinIO (self-hosted), and Cloudflare R2.
"""

from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path
from typing import BinaryIO

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

_BACKEND = os.getenv("STORAGE_BACKEND", "minio")
_BUCKET = os.getenv("STORAGE_BUCKET", "nwo-parts")
_ENDPOINT = os.getenv("STORAGE_ENDPOINT_URL") or None  # None = use AWS default
_PUBLIC_URL = os.getenv("STORAGE_PUBLIC_URL", "http://localhost:9000/nwo-parts")
_ACCESS_KEY = os.getenv("AWS_ACCESS_KEY_ID", "minioadmin")
_SECRET_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "password123")
_REGION = os.getenv("AWS_REGION", "us-east-1")


def _get_client():
    """Return a boto3 S3 client."""
    return boto3.client(
        "s3",
        endpoint_url=_ENDPOINT,
        aws_access_key_id=_ACCESS_KEY,
        aws_secret_access_key=_SECRET_KEY,
        region_name=_REGION,
        config=Config(signature_version="s3v4"),
    )


def ensure_bucket() -> None:
    """Create the bucket if it does not exist (idempotent)."""
    client = _get_client()
    try:
        client.head_bucket(Bucket=_BUCKET)
    except ClientError as e:
        if e.response["Error"]["Code"] in ("404", "NoSuchBucket"):
            client.create_bucket(Bucket=_BUCKET)
            # Make bucket public-read for MinIO/R2 (optional)
            try:
                import json
                policy = {
                    "Version": "2012-10-17",
                    "Statement": [{
                        "Effect": "Allow",
                        "Principal": {"AWS": ["*"]},
                        "Action": ["s3:GetObject"],
                        "Resource": [f"arn:aws:s3:::{_BUCKET}/*"],
                    }],
                }
                client.put_bucket_policy(Bucket=_BUCKET, Policy=json.dumps(policy))
            except Exception:
                pass  # Not all backends support bucket policies
        else:
            raise


def upload_file(
    data: bytes | BinaryIO,
    key: str,
    content_type: str = "application/octet-stream",
) -> str:
    """
    Upload bytes or a file-like object to the blob store.

    Args:
        data: File content.
        key: Object key (path within the bucket), e.g. "parts/agent-001/part-abc.stl"
        content_type: MIME type.

    Returns:
        Public URL for the uploaded file.
    """
    client = _get_client()

    if isinstance(data, bytes):
        body = io.BytesIO(data)
    else:
        body = data

    client.upload_fileobj(
        body,
        _BUCKET,
        key,
        ExtraArgs={"ContentType": content_type},
    )

    return public_url(key)


def upload_from_path(path: Path, key: str, content_type: str = "application/octet-stream") -> str:
    """Upload a local file to the blob store."""
    with open(path, "rb") as f:
        return upload_file(f, key, content_type)


def download_file(key: str) -> bytes:
    """Download a file from the blob store as bytes."""
    client = _get_client()
    response = client.get_object(Bucket=_BUCKET, Key=key)
    return response["Body"].read()


def delete_file(key: str) -> None:
    """Delete a file from the blob store."""
    client = _get_client()
    client.delete_object(Bucket=_BUCKET, Key=key)


def file_exists(key: str) -> bool:
    """Check if a key exists in the blob store."""
    client = _get_client()
    try:
        client.head_object(Bucket=_BUCKET, Key=key)
        return True
    except ClientError:
        return False


def public_url(key: str) -> str:
    """Return the public HTTP URL for an object key."""
    return f"{_PUBLIC_URL.rstrip('/')}/{key}"


def presigned_url(key: str, expires_in: int = 3600) -> str:
    """
    Generate a pre-signed download URL (useful for private buckets).
    Falls back to public URL if the bucket is public.
    """
    client = _get_client()
    try:
        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": _BUCKET, "Key": key},
            ExpiresIn=expires_in,
        )
    except Exception:
        return public_url(key)


def sha256_of_path(path: Path) -> str:
    """Return the hex SHA-256 of a local file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_of_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ── Key conventions ────────────────────────────────────────────────────────────

def part_file_key(agent_id: str, part_id: str, fmt: str) -> str:
    return f"parts/{agent_id}/{part_id}.{fmt}"


def thumbnail_key(agent_id: str, part_id: str) -> str:
    return f"thumbnails/{agent_id}/{part_id}.png"
