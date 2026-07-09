# CI/CD

## Workflows

| Workflow | Trigger | Purpose |
|----------|---------|---------|
| `pr-validation.yml` | Pull requests | Terraform validate |
| `branch-policy.yml` | PRs → `main` | Require head branch `release/*` (and based on `main`) |
| `deploy-dev.yml` | Push to `develop` or `feature/**` (app/infra paths), manual | Build images, semver tag, Terraform apply dev |

Docs-only changes under `docs/**` do not trigger dev deploy.

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

**Status checks (important):** GitHub only lets you pick checks that have **run at least once** on the repo. Until then:

1. Save the ruleset **without** “Require status checks”, **or**
2. Run workflows once (`workflow_dispatch` on **Branch policy** + merge a test PR), then edit the ruleset and add:

| Check name (exact) |
|--------------------|
| `main-from-release-only` |
| `release-contains-main` |

(Shown as **Branch policy / …** in the PR checks UI — pick from the dropdown after the first run.)

Optional: also require **PR Validation / Validate PR** from `pr-validation.yml`.

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
feature/*  →  dev  (integrate + deploy dev)
       ↓
    main     (stable integration — PRs only from release/*)
       ↓
release/vX.Y.Z  (cut from main → prod/platform deploy)
       ↓
 PR release/* → main  (after prod validated)
```

For Content Hub dev deploys: push to `develop` or `feature/**` triggers `deploy-dev.yml` (or run manually).

### 4. Optional — block direct pushes to main

In the `main` ruleset, ensure **Restrict updates** is on so nobody pushes to `main` without a PR (except bypass actors you trust).

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
