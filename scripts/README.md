# Content Hub — local build & push to ECR (until GitHub Actions)

## Quick start (dev)

```bash
./scripts/build-images.sh dev-latest
./scripts/build-sync-lambda.sh dev-latest
./scripts/push-images.sh dev-latest us-east-1 dev
# Set api_image / worker_image in dev.tfvars from push output, then:
./scripts/deploy-primary.sh dev
./scripts/smoke.sh https://devhub.communityhealth.media
```

Requires: Docker, AWS CLI credentials with ECR push access.

## Scripts

| Script | Purpose |
|--------|---------|
| `build-images.sh [VERSION]` | Build `contenthub-api` + `contenthub-worker` locally |
| `build-sync-lambda.sh [VERSION]` | Package sync jobs → `dist/sync-lambda.zip` (dev + prod) |
| `push-images.sh [VERSION] [REGION] [ENV]` | Push to ECR; creates repos if missing |
| `deploy-primary.sh [dev\|prod] [plan]` | Terraform us-east-1 — default: plan then yes/no to apply |
| `migrate-kol-headshots.sh [dev]` | EC2 PNGs → S3 assets bucket + rewrite `kols.photo_url` |
| `backfill-kol-hcp-fields.sql` | One-shot SQL: copy specialty/institution from `hcps` |

## Image tags

| ENV arg | Rolling ECR tag | tfvars file |
|---------|-----------------|-------------|
| `dev` | `dev-latest` | `dev.tfvars` |
| `prod` | `prod-latest` | `prod.tfvars` |

`VERSION` is also pushed as an immutable tag (e.g. git SHA) for traceability.

## Dockerfiles

| Path | Service |
|------|---------|
| `backend/Dockerfile` | `contenthub-api` — runs `alembic upgrade head` then uvicorn |
| `worker/Dockerfile` | Placeholder (ECS `worker_desired_count=0` until sync jobs land) |

## Local API container (optional)

```bash
docker build -t contenthub-api:local -f backend/Dockerfile backend
docker run --rm -p 8000:8000 \
  -e DATABASE_URL=postgresql+asyncpg://contenthub:contenthub@host.docker.internal:5433/contenthub_producer \
  -e PUBLIC_API_KEY=dev-change-me \
  contenthub-api:local
```
