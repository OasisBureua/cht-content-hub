# CI/CD

## Workflows

| Workflow | Trigger | Purpose |
|----------|---------|---------|
| `pr-validation.yml` | Pull requests | Terraform validate |
| `deploy-dev.yml` | Push to `main` (app/infra paths), manual | Build images, semver tag, Terraform apply dev |

Docs-only changes under `docs/**` do not trigger dev deploy.

## Development deploy

- **Environment:** `development` (GitHub Environment secrets)
- **API domain:** `devhub.communityhealth.media`
- **Terraform:** `infrastructure/terraform/environments/us-east-1`
- **Var file (CI):** `infrastructure/terraform/environments/variables/dev.github.tfvars` (non-secrets, committed)
- **Var file (local):** `dev.tfvars` (gitignored — copy from `dev.tfvars.example`)
- **Image tags:** semver `1.0.0`, `1.0.1`, … (auto-increment patch on each deploy); also pushes `dev-latest`

### One-time GitHub setup

1. **Create Environment** — Repo → Settings → Environments → **development**

2. **Add Environment secrets** (same values you use locally as `TF_VAR_*`):

| GitHub secret | Terraform variable | Local equivalent |
|---------------|-------------------|------------------|
| `AWS_ROLE_ARN` | (OIDC only) | Your IAM role ARN for GitHub Actions |
| `PUBLIC_API_KEY` | `TF_VAR_public_api_key` | `export TF_VAR_public_api_key=...` |
| `WEBHOOK_API_KEY` | `TF_VAR_webhook_api_key` | `export TF_VAR_webhook_api_key=...` |
| `JWT_SECRET` | `TF_VAR_jwt_secret` | `export TF_VAR_jwt_secret=...` |
| `INTERNAL_CACHE_SECRET` | `TF_VAR_internal_cache_secret` | `export TF_VAR_internal_cache_secret=...` |

3. **Configure OIDC** — run once from your machine (admin AWS creds):

```bash
chmod +x infrastructure/aws-github-oidc-setup.sh
GITHUB_USER=<your-github-org> ./infrastructure/aws-github-oidc-setup.sh
```

Paste the printed `AWS_ROLE_ARN` into the **development** environment secret of the same name.

Uses a **dedicated** role (`GitHubActions-ContentHub-Deploy`) — do not reuse CHT's `GitHubActions-CHT-Platform` role (wrong repo trust + ECR/state prefixes).

4. **Verify secrets** (optional):

```bash
AWS_ROLE_ARN=... PUBLIC_API_KEY=... WEBHOOK_API_KEY=... JWT_SECRET=... INTERNAL_CACHE_SECRET=... \
  ./scripts/verify-github-env-secrets.sh development
```

### Semver image tags

Each dev deploy:

1. Reads existing `x.y.z` tags on ECR `contenthub-api` (ignores `dev-latest`, `v0.0.9`, sha tags)
2. First deploy → **1.0.0**; each later deploy bumps patch (**1.0.1**, **1.0.2**, …)
3. Pushes `contenthub-api:{tag}` and `contenthub-worker:{tag}` plus `dev-latest` aliases
4. Passes exact semver to Terraform `api_image` / `worker_image`

**Note:** `scripts/smoke.sh` against `devhub` only works from CHT/VPC (ALB SG is locked down). CI waits for ECS steady state instead.

Preview next tag locally:

```bash
./scripts/next-dev-image-tag.sh contenthub-api us-east-1
```

### Manual trigger

Actions → **Deploy to Development** → Run workflow

### Local parity

```bash
export TF_VAR_public_api_key="..."
export TF_VAR_webhook_api_key="..."
export TF_VAR_jwt_secret="..."
export TF_VAR_internal_cache_secret="..."

TAG=$(./scripts/next-dev-image-tag.sh)
./scripts/build-images.sh "$TAG"
./scripts/push-images.sh "$TAG" us-east-1 dev
# Edit dev.tfvars api_image/worker_image to :$TAG or :dev-latest
./scripts/deploy-primary.sh dev
```

## Local verification

```bash
./verify.sh
cd backend && pytest -q
```

## See also

- [docs/engineering/deployment.md](../docs/engineering/deployment.md)
- [infrastructure/terraform/environments/variables/README.md](../infrastructure/terraform/environments/variables/README.md)
