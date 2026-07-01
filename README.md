# CHT Content Hub

**Community Health Technologies — Content Hub producer service** (headless API + sync jobs) powering the clinical content catalog consumed by the CHT platform.

This repo is the AWS-native rebuild of the legacy MediaHub monolith. The consumer and admin SPA live in [cht-platform-tool](https://github.com/OasisBureua/cht-platform-tool); this repo owns clips, tags, KOLs, HCP intel, and studio admin APIs.

---

## What It Does

| Area | Description |
|---|---|
| **Public catalog API** | `/api/public/*` — clips, playlists, doctors, KOLs, transcripts (CHT backend calls via `X-API-Key`) |
| **Studio admin API** | `/api/admin/studio/*` — tag editor, analytics, render pipeline (Cognito JWT from Content Hub admin) |
| **Sync jobs** | EventBridge + Lambda (target) — platform importers, tagging, cache clear → CHT |
| **Webhooks** | `/webhook/*` — ops-console ingest |

---

## Project Structure

```
cht-content-hub/
├── backend/          # FastAPI API server (contenthub-api, Python)
├── worker/           # Background sync workers (legacy ECS until Lambdas land)
├── sync/             # EventBridge / Lambda job definitions (scaffold)
├── infrastructure/   # Terraform IaC (AWS)
├── docs/             # Extended documentation
└── scripts/          # Deployment & utility scripts
```

---

## Tech Stack

### Backend (FastAPI)
- **PostgreSQL** + SQLAlchemy async + Alembic migrations
- **Python 3.11**
- Public API key auth for CHT; Cognito JWT for studio admin routes

### Worker (Python 3.11)
- **APScheduler** (ECS worker bridge until serverless cutover)
- **Boto3** — SQS / Lambda invocation (future)
- Cache invalidation → CHT `POST /internal/cache/catalog/clear`

### Infrastructure (AWS)
- **ECS Fargate** — `contenthub-api` + transitional `contenthub-worker`
- **RDS** (dev) / **Aurora Global** (prod) — producer database (never shared with CHT)
- **EventBridge + Lambda** — sync job target state
- **Terraform** — all infrastructure as code

---

## Getting Started

### Prerequisites

- Python 3.11+
- Docker Desktop
- AWS CLI (for deployment only)
- Terraform (for infrastructure only)

### 1. Start database

```bash
docker compose up -d
```

Postgres listens on **localhost:5433** (avoids conflict with CHT platform on 5432).

### 2. Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# DATABASE_URL=postgresql+asyncpg://contenthub:contenthub@localhost:5433/contenthub_producer
export PYTHONPATH=src
uvicorn main:app --app-dir src --reload --port 8002
```

### 3. Worker

```bash
cd worker
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export PYTHONPATH=../backend/src
python start_workers.py
```

Access points once running:
- API: http://localhost:8002
- Health: http://localhost:8002/health
- Public status: http://localhost:8002/api/public/status

---

## Integration with CHT Platform

| Direction | Contract |
|---|---|
| CHT → Content Hub | `GET /api/public/*` with `X-API-Key` |
| Content Hub → CHT | `POST /internal/cache/catalog/clear` after sync |
| Admin SPA → Studio | `GET/POST /api/admin/studio/*` with Cognito session JWT |

CHT env vars: `MEDIAHUB_BASE_URL`, `MEDIAHUB_API_KEY` (rename to `CONTENTHUB_*` in a future phase).

See [docs/engineering/architecture.md](docs/engineering/architecture.md) for the full target-state diagram.

---

## Local Development Helpers

```bash
./verify.sh           # lint + import tests for backend + worker
./verify.sh backend   # backend only
./verify.sh worker    # worker only

./scripts/smoke.sh                        # hits local health endpoints
./scripts/smoke.sh https://mediahub.dev.communityhealth.media  # hosted dev
```

---

## Deployment

See [docs/engineering/deployment.md](docs/engineering/deployment.md) for step-by-step deployment instructions.

Workflow details: [.github/CI_CD.md](.github/CI_CD.md).

---

## Docs

| File | Description |
|---|---|
| [docs/README.md](docs/README.md) | Documentation index |
| [docs/engineering/getting-started.md](docs/engineering/getting-started.md) | Local dev setup + env variables |
| [docs/engineering/architecture.md](docs/engineering/architecture.md) | System architecture |
| [docs/engineering/deployment.md](docs/engineering/deployment.md) | Staging and production deploys |
| [infrastructure/README.md](infrastructure/README.md) | Terraform layout |
