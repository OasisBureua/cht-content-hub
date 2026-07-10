# Content Hub — build, push, deploy

## Quick start (dev, local)

```bash
export TF_VAR_public_api_key="..."
export TF_VAR_webhook_api_key="..."
export TF_VAR_jwt_secret="..."
export TF_VAR_internal_cache_secret="..."

TAG=$(./scripts/next-ecr-image-tag.sh contenthub-dev-api us-east-1)
./scripts/build-images.sh "$TAG"
./scripts/push-images.sh "$TAG" us-east-1 dev
./scripts/deploy-primary.sh dev
./scripts/smoke.sh https://devhub.communityhealth.media   # from CHT/VPC only if ALB locked down
```

## GitHub Actions

See [.github/CI_CD.md](../.github/CI_CD.md):

| Workflow | ECR repo | Semver |
|----------|----------|--------|
| Deploy to Development | `contenthub-dev-api` | 1.0.0 … 1.0.9 → 1.1.0 … |
| Deploy to Production | `contenthub-api` | 1.0.0 … 1.0.9 → 1.1.0 … |

## Scripts

| Script | Purpose |
|--------|---------|
| `next-ecr-image-tag.sh [REPO] [REGION]` | Next semver ECR tag per repo |
| `next-dev-image-tag.sh` | Wrapper → `next-ecr-image-tag.sh` |
| `verify-github-env-secrets.sh [development\|production]` | Fail fast if GitHub secrets missing |
| `build-images.sh [VERSION]` | Build `contenthub-api` locally |
| `push-images.sh [VERSION] [REGION] [dev\|prod]` | Push to dev or prod ECR repo |
| `deploy-primary.sh [dev\|prod] [plan]` | Terraform us-east-1 (infra) |
| `deploy-api-service.sh [dev\|prod] [TAG]` | After infra-only prod apply: build, push, start ECS service |

## Prod infra-first flow

1. Set `deploy_api_ecs_service = false` in `prod.tfvars` / `prod.github.tfvars`
2. Fill VPC, subnets, ACM ARN
3. `./scripts/deploy-primary.sh prod` — creates Route53, ALB, RDS, ECS cluster + task def (no running service)
4. Delegate NS: `terraform output route53_nameservers` → GoDaddy
5. `./scripts/deploy-api-service.sh prod` — push image + create ECS service locally

## Image tags

| Deploy path | ECR repo | Rolling alias |
|-------------|----------|---------------|
| GitHub Actions dev | `contenthub-dev-api` | `dev-latest` |
| GitHub Actions prod | `contenthub-api` | `prod-latest` |
| Local dev | `contenthub-dev-api` | `dev-latest` |
| Local prod | `contenthub-api` | `prod-latest` |

Legacy tags (`v0.0.9`, sha tags) are ignored by `next-ecr-image-tag.sh`.

## Dockerfiles

| Path | Service |
|------|---------|
| `backend/Dockerfile` | `contenthub-api` — runs `alembic upgrade head` then uvicorn |

The ECS worker is retired; async work uses Lambdas (see `worker/README.md` for history).
