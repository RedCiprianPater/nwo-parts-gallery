"""
Example: publish a validated part from the Layer 1 design engine into the Layer 2 gallery.

This is the canonical agent flow — design → validate → publish.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import httpx


GALLERY_URL = os.getenv("GALLERY_URL", "http://localhost:8001")
DESIGN_URL = os.getenv("DESIGN_URL", "http://localhost:8000")


async def main():
    async with httpx.AsyncClient(timeout=120.0) as client:

        # ── Step 1: Register agent identity ───────────────────────────────
        print("Registering agent...")
        agent_r = await client.post(f"{GALLERY_URL}/agents/register", json={
            "name": "NWO Design Bot Alpha",
            "description": "Autonomous robot part design agent — NWO Robotics",
            "public_key": "demo-key-replace-with-real-ed25519-public-key",
            "key_algorithm": "ed25519",
        })
        agent_r.raise_for_status()
        agent = agent_r.json()
        agent_id = agent["id"]
        print(f"Agent ID: {agent_id}")

        # ── Step 2: Generate a part via Layer 1 ───────────────────────────
        print("\nGenerating part via Layer 1 design engine...")
        gen_r = await client.post(f"{DESIGN_URL}/design/generate", json={
            "prompt": "A servo bracket for MG996R, 4mm mounting holes on 49.5mm centres, M3 clearance holes, PLA, 30% infill",
            "provider": "anthropic",
            "backend": "openscad",
            "export_format": "stl",
            "validate": True,
            "auto_repair": True,
        })
        gen_r.raise_for_status()
        gen = gen_r.json()

        if gen["status"] != "success":
            print(f"Design failed: {gen.get('error')}")
            return

        print(f"Part generated: job {gen['job_id']}")
        print(f"Validation passed: {gen.get('validation', {}).get('passed')}")

        # ── Step 3: Download the file from Layer 1 ────────────────────────
        print("\nDownloading generated STL...")
        file_r = await client.get(f"{DESIGN_URL}{gen['file_url']}")
        file_r.raise_for_status()
        file_bytes = file_r.content
        print(f"File size: {len(file_bytes) / 1024:.1f} KB")

        # ── Step 4: Publish to Layer 2 gallery ────────────────────────────
        print("\nPublishing to parts gallery...")
        metadata = {
            "name": "MG996R Servo Bracket",
            "category": "joint",
            "body_zone": "arm",
            "description": "Parametric bracket for MG996R servo motor. M3 clearance holes, 49.5mm mounting centre distance.",
            "tags": ["servo", "bracket", "MG996R", "arm", "joint"],
            "material_hints": ["PLA", "PETG"],
            "print_settings": {
                "infill_pct": 30,
                "layer_height_mm": 0.2,
                "supports_required": False,
                "connector_standard": "M3",
                "tolerance_class": "standard",
            },
            "license": "CC0",
            "generator": "NWO Design Engine v0.1.0",
            "llm_provider": gen.get("provider"),
            "llm_model": gen.get("model"),
            "validation_passed": gen.get("validation", {}).get("passed"),
            "validation_report": gen.get("validation") or {},
        }

        pub_r = await client.post(
            f"{GALLERY_URL}/parts/publish",
            headers={"X-Agent-ID": agent_id},
            files={"file": ("bracket.stl", file_bytes, "model/stl")},
            data={"metadata": json.dumps(metadata)},
        )
        pub_r.raise_for_status()
        pub = pub_r.json()

        print(f"✓ Published: {pub['name']} v{pub['version']}")
        print(f"  Part ID  : {pub['part_id']}")
        print(f"  File URL : {pub['file_url']}")
        print(f"  Gallery  : {GALLERY_URL}/gallery/{pub['part_id']}")

        # ── Step 5: Search for it ─────────────────────────────────────────
        print("\nSearching gallery for 'servo bracket'...")
        search_r = await client.get(f"{GALLERY_URL}/parts/search", params={
            "q": "servo bracket M3",
            "category": "joint",
            "limit": 5,
        })
        search_r.raise_for_status()
        results = search_r.json()
        print(f"Found {results['total']} result(s):")
        for r in results["results"]:
            print(f"  - {r['name']} v{r['version']} [{r['license']}] ↓{r['download_count']}")


if __name__ == "__main__":
    asyncio.run(main())
