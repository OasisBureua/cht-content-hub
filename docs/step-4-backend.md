# Step 4 — Producer backend (KOL + HCP Intel)

Step-by-step plan. **Step 4.1 is done in this repo.**

| Step | Task | Status |
|------|------|--------|
| **4.1** | Alembic + baseline migration (KOL + HCP Intel tables) | ✅ |
| **4.2** | `POST /api/public/hcp/upsert` (CHT registration sync) | ✅ |
| **4.3** | Dockerfile + ECR image for `contenthub-api` | ✅ |
| **4.4** | `pg_dump` restore from MediaHub → Content Hub RDS | ✅ |
| **4.5** | Wire Alembic into ECS deploy + smoke test on devhub | ⬜ |

## 4.1 — Migrations (done)

**What was added**

- `backend/alembic.ini`, `backend/migrations/`
- `0001_contenthub_baseline.py` — creates all tables in `models/` + `hcp_intel/models.py`
- Minimal `users` stub table (FK target for HCP Intel admin fields)
- Removed `create_all` from `main.py` — schema is Alembic-managed

**Run migrations (PostgreSQL required)**

```bash
cd backend
source .venv/bin/activate
pip install -r requirements.txt

# Local Docker Postgres
export DATABASE_URL=postgresql+asyncpg://contenthub:contenthub@localhost:5433/contenthub_producer
alembic upgrade head
alembic current   # should show 0001_contenthub_baseline (head)
```

**Notes**

- Migrations target **PostgreSQL** (partial indexes, JSONB, arrays). Tests still use in-memory SQLite via `tests/schema.py` — no Docker needed for `pytest`.
- We use a **single baseline** migration from current ORM models, not the full MediaHub migration chain (which includes clips, posts, LinkedIn ads, etc.).

## 4.2 — HCP upsert (done)

`POST /api/public/hcp/upsert` in `public/router.py` + `services/hcp_upsert.py`.

- Auth: `X-API-Key` (same as KOL routes)
- Request: snake_case body from CHT `mediahub-sync.service.ts` (`npi`, `first_name`, `last_name`, optional `email`, `specialty`, `city`, `state`, `zip`, `institution`, `source`)
- Response: `{ "created": bool, "npi": "..." }` — CHT only reads `created`
- Field mapping: `specialty` → `hcps.taxonomy`, `institution` → `hcps.hospital_affiliations`

## 4.3 — Docker + ECR (done)

```bash
./scripts/build-images.sh dev-latest
./scripts/push-images.sh dev-latest us-east-1 dev
# → set api_image / worker_image in dev.tfvars
```

See [scripts/README.md](../scripts/README.md).

## 4.4 — Data restore

Use `scripts/pg_dump_restore.sh` to copy KOL + HCP Intel data from MediaHub dev RDS into Content Hub dev RDS after infra is up.

## 4.5 — Deploy + smoke

After ACM cert ISSUED + images pushed + `terraform apply`:

```bash
./scripts/deploy-primary.sh dev apply
# Delegate NS: terraform output route53_nameservers  → GoDaddy parent zone
./scripts/smoke.sh https://devhub.communityhealth.media
```
