"""
NWO Parts Gallery CLI.

Usage:
    nwo-gallery serve
    nwo-gallery migrate
    nwo-gallery seed-data
    nwo-gallery reindex-embeddings
    nwo-gallery stats
"""

from __future__ import annotations

import asyncio
import os

import click
from rich.console import Console
from rich.table import Table

console = Console()


@click.group()
def cli():
    """NWO Robotics Parts Gallery — Layer 2."""


@cli.command()
@click.option("--host", default=None)
@click.option("--port", default=None, type=int)
@click.option("--reload", is_flag=True)
def serve(host, port, reload):
    """Start the gallery API + HTML server."""
    import uvicorn
    _host = host or os.getenv("API_HOST", "0.0.0.0")
    _port = port or int(os.getenv("API_PORT", "8001"))
    console.print(f"\n[bold]NWO Parts Gallery[/bold] → http://{_host}:{_port}")
    console.print(f"  Gallery : http://{_host}:{_port}/gallery")
    console.print(f"  API docs: http://{_host}:{_port}/docs\n")
    uvicorn.run("src.api.main:app", host=_host, port=_port, reload=reload)


@cli.command()
def migrate():
    """Run Alembic database migrations."""
    import subprocess
    console.print("Running Alembic migrations...")
    result = subprocess.run(["alembic", "upgrade", "head"], capture_output=True, text=True)
    if result.returncode == 0:
        console.print("[green]✓ Migrations complete[/green]")
    else:
        console.print(f"[red]✗ Migration failed:[/red]\n{result.stderr}")


@cli.command()
def reindex_embeddings():
    """Regenerate embeddings for all parts that are missing them."""
    asyncio.run(_reindex())


async def _reindex():
    from sqlalchemy import select, update
    from src.models.database import AsyncSessionLocal
    from src.models.orm import Part
    from src.search.embeddings import build_embedding_text, get_embedding_provider

    provider = get_embedding_provider()
    async with AsyncSessionLocal() as db:
        parts = (await db.execute(
            select(Part).where(Part.embedding.is_(None), Part.is_deprecated == False)
        )).scalars().all()

        console.print(f"Re-indexing {len(parts)} parts...")
        for i, part in enumerate(parts):
            try:
                text = build_embedding_text(
                    name=part.name,
                    description=part.description,
                    category=part.category,
                    body_zone=part.body_zone,
                    tags=part.tags or [],
                    material_hints=part.material_hints or [],
                    connector_standard=part.connector_standard,
                )
                vec = await provider.embed(text)
                if vec:
                    await db.execute(
                        update(Part).where(Part.id == part.id).values(embedding=vec)
                    )
                if (i + 1) % 10 == 0:
                    await db.commit()
                    console.print(f"  {i+1}/{len(parts)}...")
            except Exception as e:
                console.print(f"  [yellow]⚠[/yellow] {part.id}: {e}")

        await db.commit()
        console.print(f"[green]✓[/green] Re-indexed {len(parts)} parts.")


@cli.command()
def stats():
    """Print gallery statistics."""
    asyncio.run(_stats())


async def _stats():
    from sqlalchemy import func, select
    from src.models.database import AsyncSessionLocal
    from src.models.orm import Agent, Part

    async with AsyncSessionLocal() as db:
        total_parts = (await db.execute(select(func.count()).select_from(Part))).scalar()
        total_agents = (await db.execute(select(func.count()).select_from(Agent))).scalar()
        total_dl = (await db.execute(select(func.sum(Part.download_count)))).scalar() or 0
        validated = (await db.execute(
            select(func.count()).select_from(Part).where(Part.validation_passed == True)
        )).scalar()
        with_embeddings = (await db.execute(
            select(func.count()).select_from(Part).where(Part.embedding.is_not(None))
        )).scalar()

    table = Table(title="NWO Parts Gallery Stats")
    table.add_column("Metric", style="bold")
    table.add_column("Value", style="green")
    table.add_row("Total parts", str(total_parts))
    table.add_row("Total agents", str(total_agents))
    table.add_row("Total downloads", str(total_dl))
    table.add_row("Validated parts", str(validated))
    table.add_row("Parts with embeddings", str(with_embeddings))
    console.print(table)


@cli.command()
def seed_data():
    """Insert sample parts and a demo agent for local development."""
    asyncio.run(_seed())


async def _seed():
    from src.models.database import AsyncSessionLocal, create_tables
    from src.models.orm import Agent, Part
    import uuid, hashlib

    await create_tables()

    async with AsyncSessionLocal() as db:
        agent = Agent(
            id=str(uuid.uuid4()),
            name="NWO Demo Agent",
            description="Demo agent for local development seeding",
            public_key="demo-public-key-" + hashlib.sha256(b"demo").hexdigest()[:16],
            key_algorithm="ed25519",
        )
        db.add(agent)
        await db.flush()

        sample_parts = [
            ("MG996R Servo Bracket", "joint", "arm", "Parametric servo bracket for MG996R, M3 mounting holes", ["servo", "bracket", "MG996R"]),
            ("6-DOF Arm Frame Rail", "frame", "arm", "Structural rail for 6-DOF manipulator arm assembly", ["arm", "rail", "structural"]),
            ("Omni Wheel Hub 60mm", "wheel", "base", "60mm omni-wheel hub, press-fit bearings, M4 axle", ["wheel", "omni", "hub"]),
            ("Pan-Tilt Camera Mount", "sensor_mount", "head", "2-axis pan-tilt bracket for camera or LIDAR sensors", ["camera", "pan-tilt", "sensor"]),
            ("Gripper Finger Pair", "gripper", "arm", "Parallel jaw gripper fingers, 40mm stroke, TPU-compatible", ["gripper", "finger", "jaw"]),
        ]

        for name, cat, zone, desc, tags in sample_parts:
            part = Part(
                id=str(uuid.uuid4()),
                agent_id=agent.id,
                name=name,
                slug=name.lower().replace(" ", "-"),
                version=1,
                is_latest=True,
                category=cat,
                body_zone=zone,
                description=desc,
                tags=tags,
                file_key=f"parts/{agent.id}/demo.stl",
                file_format="stl",
                file_size_bytes=42000,
                file_hash_sha256=hashlib.sha256(name.encode()).hexdigest(),
                material_hints=["PLA", "PETG"],
                infill_pct=30,
                supports_required=False,
                license="CC0",
                generator="NWO Design Engine v0.1.0",
                validation_passed=True,
            )
            db.add(part)

        await db.commit()
        console.print(f"[green]✓[/green] Seeded demo agent + {len(sample_parts)} parts.")


if __name__ == "__main__":
    cli()
