# Content Hub — build, push, deploy

## Quick start (dev, local)

```bash
export TF_VAR_public_api_key="..."
export TF_VAR_webhook_api_key="..."
export TF_VAR_jwt_secret="..."
export TF_VAR_internal_cache_secret="..."

TAG=$(./scripts/next-dev-image-tag.sh)
./scripts/build-images.sh "$TAG"
./scripts/push-images.sh "$TAG" us-east-1 dev
# Set api_image / worker_image in dev.tfvars from push output, then:
./scripts/deploy-primary.sh dev
./scripts/smoke.sh https://devhub.communityhealth.media   # from CHT/VPC only if ALB locked down
```

## GitHub Actions (preferred for dev)

See [.github/CI_CD.md](../.github/CI_CD.md) — **Deploy to Development** workflow:

- Semver tags `1.0.0`, `1.0.1`, … via `next-dev-image-tag.sh`
- Secrets in GitHub Environment **development** (same as local `TF_VAR_*`)
- Infra from committed `dev.github.tfvars`

Requires: Docker, AWS CLI credentials with ECR push access (local only).

## Scripts

| Script | Purpose |
|--------|---------|
| `next-dev-image-tag.sh [REPO] [REGION]` | Next semver ECR tag (1.0.0 → 1.0.1 → …) |
| `verify-github-env-secrets.sh development` | Fail fast if GitHub secrets missing |
| `build-images.sh [VERSION]` | Build `contenthub-api` + `contenthub-worker` locally |
| `build-sync-lambda.sh [VERSION]` | Package sync jobs → `dist/sync-lambda.zip` (dev + prod) |
| `push-images.sh [VERSION] [REGION] [ENV]` | Push to ECR; creates repos if missing |
| `deploy-primary.sh [dev\|prod] [plan]` | Terraform us-east-1 — default: plan then yes/no to apply |
| `migrate-kol-headshots.sh [dev]` | EC2 PNGs → S3 assets bucket + rewrite `kols.photo_url` |
| `backfill-kol-hcp-fields.sql` | One-shot SQL: copy specialty/institution from `hcps` |

## Image tags

| Deploy path | Tag scheme | tfvars |
|-------------|------------|--------|
| **GitHub Actions dev** | Semver `1.0.0`, `1.0.1`, … + `dev-latest` | `dev.github.tfvars` |
| **Local dev** | Any tag + `dev-latest` rolling | `dev.tfvars` |
| **Prod** | `prod-latest` + immutable tag | `prod.tfvars` |

Legacy tags (`v0.0.9`, sha tags) are ignored by `next-dev-image-tag.sh`.

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
