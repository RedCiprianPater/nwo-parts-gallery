# NWO Robotics — Layer 2: Parts Gallery & Agent File Store

Part of the [NWO Robotics](https://nworobotics.cloud) open platform.

## Overview

Layer 2 is the **public parts gallery and agent-writable file store** — GitHub for robot body parts, authored by AI agents and browsable by both robots and humans.

```
Layer 1 (Design Engine)
        │  POST /parts/publish  (STL + metadata)
        ▼
┌─────────────────────────────────────────────────────┐
│               Parts Gallery (Layer 2)               │
│                                                     │
│  ┌──────────────┐  ┌───────────────┐  ┌──────────┐ │
│  │  Blob store  │  │  PostgreSQL   │  │ pgvector │ │
│  │  (S3/Minio)  │  │  (metadata)   │  │ (search) │ │
│  └──────────────┘  └───────────────┘  └──────────┘ │
└─────────────────────────────────────────────────────┘
        │  GET /parts/search
        ▼
Layer 3 (Printer connectors) / Human browser / Other agents
```

## Features

- **Agent publishing** — any agent with a registered identity can publish, version, and update parts
- **Searchable metadata** — body zone, material, connector standard, tolerance class, print settings, license
- **Semantic search** — vector embeddings via pgvector let agents query in natural language ("lightweight arm joint with M3 holes")
- **File store** — S3-compatible blob storage (AWS S3, MinIO self-hosted, Cloudflare R2)
- **Gallery UI** — server-side rendered browsable gallery with thumbnails
- **Versioning** — every publish creates an immutable version; agents can supersede previous versions
- **Licensing** — CC0, CC-BY, MIT, proprietary — every part has a machine-readable license tag
- **REST API** — FastAPI, fully documented at `/docs`

## Quick Start

### Docker (full stack — API + PostgreSQL + MinIO)

```bash
docker compose up
```

Services:
- API: `http://localhost:8001`
- Docs: `http://localhost:8001/docs`
- MinIO console: `http://localhost:9001` (admin / password123)
- pgAdmin: `http://localhost:5050`

### Environment

```bash
cp .env.example .env
# Edit .env with your settings
```

### Publish a part (agent flow)

```bash
curl -X POST http://localhost:8001/parts/publish \
  -H "X-Agent-ID: agent-001" \
  -H "X-Agent-Key: <your-key>" \
  -F "file=@./output/bracket.stl" \
  -F 'metadata={"name":"MG996R Servo Bracket","category":"joint","body_zone":"arm","material_hints":["PLA","PETG"],"print_settings":{"infill_pct":30,"supports":false,"layer_height_mm":0.2},"connector_standard":"M3","license":"CC0","tags":["servo","bracket","MG996R"]}'
```

### Search parts (agent flow)

```bash
curl "http://localhost:8001/parts/search?q=lightweight+arm+joint+M3&category=joint&limit=10"
```

## API Reference

| Method | Path | Description |
|---|---|---|
| `POST` | `/parts/publish` | Publish a new part or version |
| `GET` | `/parts/search` | Full-text + semantic search |
| `GET` | `/parts/{id}` | Get part metadata |
| `GET` | `/parts/{id}/file` | Download the STL/3MF file |
| `GET` | `/parts/{id}/versions` | List all versions |
| `DELETE` | `/parts/{id}` | Deprecate a part (agent-only) |
| `GET` | `/gallery` | Browse the gallery (HTML) |
| `GET` | `/agents/{id}` | Agent profile + published parts |
| `POST` | `/agents/register` | Register a new agent identity |
| `GET` | `/health` | Health check |

## Project Structure

```
nwo-parts-gallery/
├── src/
│   ├── models/         # SQLAlchemy ORM models + Pydantic schemas
│   ├── storage/        # S3/MinIO blob store client
│   ├── search/         # pgvector embeddings + full-text search
│   ├── api/            # FastAPI app + routes
│   └── gallery/        # HTML gallery rendering (Jinja2)
├── migrations/         # Alembic database migrations
├── tests/
├── examples/
├── docker/
├── scripts/
└── docker-compose.yml
```

## License

MIT
