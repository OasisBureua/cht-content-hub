# contenthub-api

Producer FastAPI service. **Step 3:** public KOL routes (`/api/public/kols*`).

## Local run

Requires **Python 3.11+** and Postgres (`docker compose up -d` from repo root).

```bash
docker compose up -d

cd backend
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # set PUBLIC_API_KEY

cd src
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

```bash
export PUBLIC_API_KEY=dev-change-me
curl -H "X-API-Key: $PUBLIC_API_KEY" http://localhost:8000/api/public/kols
curl http://localhost:8000/health
```

## Tests

No Docker required — tests use in-memory SQLite by default.

```bash
cd backend && source .venv/bin/activate
pip install -r requirements.txt
pytest tests/ -v
```

## Migrations (Step 4.1)

PostgreSQL required (`docker compose up -d` from repo root):

```bash
cd backend
export DATABASE_URL=postgresql+asyncpg://contenthub:contenthub@localhost:5433/contenthub_producer
alembic upgrade head
```

See [docs/step-4-backend.md](../docs/step-4-backend.md) for the full Step 4 checklist.

### Coverage

| Module | Test file |
|--------|-----------|
| `config`, `public/deps`, `public/limits` | `test_config_and_deps.py` |
| `utils/kol_public` | `test_kol_public_utils.py` |
| `utils/time` | `test_utils_time.py` |
| `services/kol_regions` | `test_kol_regions.py` |
| `services/kol_queries` | `test_kol_queries.py` |
| Public HTTP routes + rate limits | `test_public_api.py` |
| `request_logger` | `test_request_logger.py` |

## Step 3 routes

| Method | Path |
|--------|------|
| GET | `/api/public/kols` |
| GET | `/api/public/kols/{slug}` |
| GET | `/api/public/kols/{slug}/publications` |

Auth: header `X-API-Key` (must match `PUBLIC_API_KEY` / Terraform `public_api_key`).

Next: [docs/kol-hcp-intel-migration.md](../docs/kol-hcp-intel-migration.md) — HCP upsert, admin studio, migrations.
