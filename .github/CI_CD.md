# CI/CD

## Workflows

| Workflow | Trigger | Purpose |
|----------|---------|---------|
| `pr-validation.yml` | Pull requests | Terraform validate |
| `branch-policy.yml` | PRs → `main` | Require head branch `release/*` (and based on `main`) |
| `deploy-dev.yml` | Push to `develop` / `feature/**`, manual | Build API → `contenthub-dev-api`, Terraform apply dev |
| `deploy-prod.yml` | Push to `main` / `release/**`, manual | Build API → `contenthub-api`, Terraform apply prod |

Docs-only changes under `docs/**` do not trigger deploys.

## ECR repositories

| Repo | Environment | Rolling alias |
|------|-------------|---------------|
| `contenthub-dev-api` | dev | `dev-latest` |
| `contenthub-api` | prod | `prod-latest` |

Each repo maintains its own semver counter: **1.0.0**, **1.0.1**, … (patch bump on every deploy). The ECS worker image is retired — only the API image is built and pushed.

## Branch flow (main ← release only)

GitHub **rulesets alone cannot** restrict which source branch merges into `main`. Use **rulesets + required status check**:

### 1. Ruleset — protect `main`

Repo → **Settings → Rules → Rulesets → New branch ruleset**

| Setting | Value |
|---------|--------|
| Name | `Protect main` |
| Enforcement | Active |
| Target branches | `main` (default branch) |
| Restrict deletions | ✓ |
| Block force pushes | ✓ |
| Require a pull request | ✓ (1 approval, optional code owners) |
| Require status checks | ✓ — add **`main-from-release-only`** and **`release-contains-main`** (after first workflow run) |
| Require branches up to date | ✓ (recommended) |

Do **not** allow broad bypass on this ruleset.

### 2. Ruleset — protect `release/*`

New ruleset:

| Setting | Value |
|---------|--------|
| Name | `Protect release branches` |
| Target branches | `release/**` |
| Restrict deletions | ✓ |
| Block force pushes | ✓ |
| Require a pull request | ✓ (for merges between release branches if needed) |
| Restrict updates | Optional — limit who can push directly to `release/*` |

**Creating `release/*` from `main`:** GitHub has no single “must branch off main” toggle. Enforce with:

- Team process: `git checkout main && git pull && git checkout -b release/v1.0.0`
- CI job **`release branch includes main`** (in `branch-policy.yml`) on PRs to `main`

### 3. Recommended git flow (matches CHT)

```text
feature/*  →  develop  (integrate + deploy dev)
       ↓
    main     (stable integration — PRs only from release/*)
       ↓
release/vX.Y.Z  (cut from main → prod/platform deploy)
       ↓
 PR release/* → main  (after prod validated)
```

## Development deploy

- **Environment:** `development` (GitHub Environment secrets)
- **ECR:** `contenthub-dev-api`
- **API domain:** `devhub.communityhealth.media`
- **Terraform:** `infrastructure/terraform/environments/us-east-1`
- **Var file (CI):** `infrastructure/terraform/environments/variables/dev.github.tfvars`
- **Var file (local):** `dev.tfvars` (gitignored — copy from `dev.tfvars.example`)

### One-time GitHub setup (dev)

1. **Create Environment** — Repo → Settings → Environments → **development**

2. **Add Environment secrets:**

| GitHub secret | Terraform variable |
|---------------|-------------------|
| `AWS_ROLE_ARN` | (OIDC only) |
| `PUBLIC_API_KEY` | `TF_VAR_public_api_key` |
| `WEBHOOK_API_KEY` | `TF_VAR_webhook_api_key` |
| `JWT_SECRET` | `TF_VAR_jwt_secret` |
| `INTERNAL_CACHE_SECRET` | `TF_VAR_internal_cache_secret` |

3. **Configure OIDC** — run once from your machine (admin AWS creds):

```bash
chmod +x infrastructure/aws-github-oidc-setup.sh
GITHUB_USER=<your-github-org> GITHUB_ENVIRONMENTS=development,production \
  ./infrastructure/aws-github-oidc-setup.sh
```

Paste the printed `AWS_ROLE_ARN` into **both** `development` and `production` environment secrets (same role; trust allows both environments).

4. **Verify secrets** (optional):

```bash
AWS_ROLE_ARN=... PUBLIC_API_KEY=... WEBHOOK_API_KEY=... JWT_SECRET=... INTERNAL_CACHE_SECRET=... \
  ./scripts/verify-github-env-secrets.sh development
```

### Semver image tags (dev)

Each dev deploy:

1. Reads existing `x.y.z` tags on ECR **`contenthub-dev-api`**
2. First deploy after reset → **1.0.0**; each later deploy bumps patch
3. Pushes `{tag}` and `dev-latest`
4. Passes exact semver to Terraform `api_image`

Preview next tag:

```bash
./scripts/next-ecr-image-tag.sh contenthub-dev-api us-east-1
```

## Production deploy

- **Environment:** `production` (separate GitHub Environment secrets)
- **ECR:** `contenthub-api`
- **API domain:** `contenthub.communityhealth.media`
- **Var file (CI):** `prod.github.tfvars` — fill VPC, subnets, SG, and ACM ARN before first prod apply

Semver works the same as dev but against **`contenthub-api`** independently:

```bash
./scripts/next-ecr-image-tag.sh contenthub-api us-east-1
```

### Manual trigger

- Dev: Actions → **Deploy to Development**
- Prod: Actions → **Deploy to Production**

### Local parity

```bash
export TF_VAR_public_api_key="..."
export TF_VAR_webhook_api_key="..."
export TF_VAR_jwt_secret="..."
export TF_VAR_internal_cache_secret="..."

TAG=$(./scripts/next-ecr-image-tag.sh contenthub-dev-api us-east-1)
./scripts/build-images.sh "$TAG"
./scripts/push-images.sh "$TAG" us-east-1 dev
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
