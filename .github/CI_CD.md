# CI/CD

## Workflows

| Workflow | Trigger | Purpose |
|----------|---------|---------|
| `pr-validation.yml` | Pull requests | Terraform validate |
| `branch-policy.yml` | PRs → `main`, push `release/**` | Require `release/*` head; release must branch from `develop` |
| `deploy-dev.yml` | Push to `develop` / `feature/**`, manual | Build API → `contenthub-dev-api`, Terraform apply dev |
| `deploy-prod.yml` | Merged `release/*` → `main`, manual | Build API → Terraform apply prod (use1 + use2 DR) |

Docs-only changes under `docs/**` do not trigger deploys.

## ECR repositories

| Repo | Environment | Rolling alias |
|------|-------------|---------------|
| `contenthub-dev-api` | dev | `dev-latest` |
| `contenthub-api` | prod | `prod-latest` |

Each repo maintains its own semver counter. **develop** and **feature/** deploys both use `contenthub-dev-api` — one shared sequence (not per-branch tags). Prod uses `contenthub-api` independently.

Bump rule: increment the patch digit each deploy (`1.0.0` → `1.0.1` → … → `1.0.9` → `1.1.0` → … → `1.9.9` → `2.0.0`). The ECS worker image is retired — only the API image is built and pushed.

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
| Require status checks | ✓ — add **`main-from-release-only`** and **`release-from-develop`** (after first workflow run) |
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

- Team process: `git checkout develop && git pull && git checkout -b release/v1.0.0`
- CI job **`release-from-develop`** (in `branch-policy.yml`) on PRs to `main`

### 3. Recommended git flow

```text
feature/*  →  develop           (integrate + deploy dev)
develop    →  release/vX.Y.Z    (cut release branch)
release/*  →  main              (merge PR → deploy-prod.yml)
```

Prod deploy runs when a **`release/*` PR merges to `main`**, or via manual **Deploy to Production**. Pushing to `main` or `release/*` alone does not deploy prod.

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

**Platform integrations (optional — add when enabling LinkedIn/YouTube sync or AI insights):**

| GitHub secret | Terraform variable | Local equivalent |
|---------------|-------------------|------------------|
| `OPENAI_API_KEY` | `TF_VAR_openai_api_key` | inline in `dev.tfvars` or export |
| `ANTHROPIC_API_KEY` | `TF_VAR_anthropic_api_key` | inline in `dev.tfvars` or export |
| `LINKEDIN_ADS_CLIENT_ID` | `TF_VAR_linkedin_ads_client_id` | inline in `dev.tfvars` or export |
| `LINKEDIN_ADS_CLIENT_SECRET` | `TF_VAR_linkedin_ads_client_secret` | inline in `dev.tfvars` or export |
| `LINKEDIN_ADS_REDIRECT_URI` | `TF_VAR_linkedin_ads_redirect_uri` | inline in `dev.tfvars` or export |
| `LINKEDIN_ADS_SCOPES` | `TF_VAR_linkedin_ads_scopes` | inline in `dev.tfvars` or export |
| `LINKEDIN_AD_ACCOUNT_ID` | `TF_VAR_linkedin_ad_account_id` | inline in `dev.tfvars` or export |
| `LINKEDIN_CLIENT_ID` | `TF_VAR_linkedin_client_id` | inline in `dev.tfvars` or export |
| `LINKEDIN_CLIENT_SECRET` | `TF_VAR_linkedin_client_secret` | inline in `dev.tfvars` or export |
| `LINKEDIN_REDIRECT_URI` | `TF_VAR_linkedin_redirect_uri` | inline in `dev.tfvars` or export |
| `LINKEDIN_SCOPES` | `TF_VAR_linkedin_scopes` | inline in `dev.tfvars` or export |
| `LINKEDIN_ORG_URN` | `TF_VAR_linkedin_org_urn` | inline in `dev.tfvars` or export |
| `YOUTUBE_API_KEY` | `TF_VAR_youtube_api_key` | inline in `dev.tfvars` or export |
| `YOUTUBE_CHANNEL_ID` | `TF_VAR_youtube_channel_id` | inline in `dev.tfvars` or export |
| `YOUTUBE_CHANNEL_HANDLE` | `TF_VAR_youtube_channel_handle` | inline in `dev.tfvars` or export |
| `X_BEARER_TOKEN` | `TF_VAR_x_bearer_token` | inline in `dev.tfvars` or export |
| `X_ACCOUNT_HANDLE` | `TF_VAR_x_account_handle` | inline in `dev.tfvars` or export |
| `WORDPRESS_WEBHOOK_SECRET` | `TF_VAR_wordpress_webhook_secret` | inline in `dev.tfvars` or export |

Empty optional secrets are OK — deploy still succeeds; platform sync features stay disabled until values are set.

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

1. Reads existing semver tags on ECR **`contenthub-dev-api`** (highest `x.y.z`)
2. First deploy after reset → **1.0.0**; each later deploy bumps one step (`1.0.9` → `1.1.0`)
3. Pushes `{tag}` and `dev-latest`
4. Passes exact semver to Terraform `api_image`

Preview next tag:

```bash
./scripts/next-ecr-image-tag.sh contenthub-dev-api us-east-1
```

## Production deploy

- **GitHub Environment:** `production` (required — workflow job uses `environment: production`)
- **ECR:** `contenthub-api` (replicated to us-east-2)
- **API domain:** `contenthub.communityhealth.media`
- **Terraform:** `us-east-1` + `us-east-2` DR stacks
- **Var file (CI):** `infrastructure/terraform/environments/variables/prod.github.tfvars`
- **Secrets (CI):** GitHub Environment **production** → `TF_VAR_*` (see below)
- **Local secrets:** `prod.tfvars` (gitignored) — not used by CI

### Trigger

| Trigger | Deploys? |
|---------|----------|
| Merge PR `release/v1.0.0` → `main` | Yes |
| Manual **Deploy to Production** | Yes |
| Push to `release/*` (no merge) | No |
| Push to `main` directly | No |

### One-time GitHub setup (production)

1. **Create Environment** — Repo → Settings → Environments → **production**

2. **Required Environment secrets:**

| GitHub secret | Terraform variable | Notes |
|---------------|-------------------|--------|
| `AWS_ROLE_ARN` | (OIDC) | Same role as dev if OIDC script used both envs |
| `PUBLIC_API_KEY` | `TF_VAR_public_api_key` | Must match CHT `CONTENTHUB_API_KEY` |
| `WEBHOOK_API_KEY` | `TF_VAR_webhook_api_key` | |
| `JWT_SECRET` | `TF_VAR_jwt_secret` | |
| `INTERNAL_CACHE_SECRET` | `TF_VAR_internal_cache_secret` | Shared with CHT cache clear |

3. **Optional** (platform sync / AI — same as dev):

`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `LINKEDIN_*`, `YOUTUBE_*`, `X_*`, `WORDPRESS_WEBHOOK_SECRET`, `LINKEDIN_ADS_ACCESS_TOKEN`

4. **OIDC** (if not done for dev):

```bash
GITHUB_USER=<org> GITHUB_ENVIRONMENTS=development,production \
  ./infrastructure/aws-github-oidc-setup.sh
```

5. **Verify:**

```bash
./scripts/verify-github-env-secrets.sh production
```

### First prod release (recommended)

```bash
git checkout develop && git pull
git checkout -b release/v1.0.0
# merge feature branch if needed
git push -u origin release/v1.0.0
# Open PR release/v1.0.0 → main (passes main-from-release-only + release-from-develop)
# After merge → deploy-prod.yml runs automatically
```

Or dry-run first: Actions → **Deploy to Production** → check **Plan only**.

### What deploy-prod does

1. Build + push `contenthub-api` image (use1)
2. Wait for ECR replication to use2
3. `terraform plan` use1 + use2 DR (with approval gate)
4. `terraform apply` both regions (`deploy_api_ecs_service` / `dr_deploy_api_ecs_service` from `prod.github.tfvars`)
5. Wait for ECS services stable

`enable_route53_failover` stays **false** in `prod.github.tfvars` until you arm failover manually (`./scripts/arm-route53-failover.sh`).

Semver works the same as dev but against **`contenthub-api`**:

```bash
./scripts/next-ecr-image-tag.sh contenthub-api us-east-1
```

### Manual trigger

- Dev: Actions → **Deploy to Development**
- Prod: Actions → **Deploy to Production** (optional **Plan only** checkbox)

### Local parity (infra-only; ECS via CI)

```bash
# Infra without ECS service (overrides prod.github.tfvars deploy flags):
./scripts/deploy-contenthub-infra-local.sh plan-only
./scripts/deploy-contenthub-secondary.sh plan-only

# Or export TF_VAR_* and use deploy-primary.sh with prod.github.tfvars + prod.tfvars
```

## Local verification

```bash
./verify.sh
cd backend && pytest -q
```

## See also

- [docs/engineering/deployment.md](../docs/engineering/deployment.md)
- [infrastructure/terraform/environments/variables/README.md](../infrastructure/terraform/environments/variables/README.md)
