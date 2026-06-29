# cht-content-hub

The producer service powering Content Hub — clips, tags, KOLs, HCP intel, and the studio admin UI. Pairs with `cht-platform-tool` (the consumer service) under a single Content Hub SPA at `contenthub.communityhealth.media`.

## Architectural boundary

```
                  contenthub.communityhealth.media
                       (CloudFront → S3 SPA)
                               │
                       ┌───────┴────────┐
                       │                │
                       ▼                ▼
              /api/admin/platform/*    /api/admin/studio/*   /api/public/*
                       │                │
                       ▼                ▼
              cht-platform-backend   cht-content-hub-api  (this repo)
                       │                │
                       ▼                ▼
              CHT Aurora Global    Producer Aurora Global
              (users, CME)         (clips, tags, KOLs, HCP intel)
```

**Rule (locked):** `cht-platform-backend` never connects to the producer DB. HTTP only.

## Status

Initial scaffolding. Directory structure and placeholder READMEs only — no application code, no Terraform yet.

## Repo structure

| Path | Purpose |
|---|---|
| `infra/` | Terraform infrastructure-as-code. Environment-specific config in `infra/environments/`, reusable modules in `infra/modules/`. |
| `services/api/` | The producer FastAPI surface that runs on ECS Fargate. Owns `/api/public/*` (consumer-facing catalog) and `/api/admin/studio/*` (CHM staff studio UI). Does NOT own `/api/admin/platform/*` — that's on `cht-platform-backend`. |
| `services/lambdas/<function>/` | Event-driven Lambdas, one directory per function, grouped by function (not by research-paper domain numbering). |
| `services/step_functions/` | Step Function state machine definitions for multi-step orchestration. |
| `services/shared/` | Code shared across the API and Lambdas. `post_tagger` distributes as a Lambda Layer; other modules vendor at build time. |
| `migrations/` | Forward migrations for the producer Aurora schema. Alembic. |
| `docs/` | Architecture decision records, runbooks, conventions. |
| `scripts/` | Local dev helpers and one-shot operational scripts. |
| `tests/` | Integration and end-to-end tests. |

See each subdirectory's README for purpose-specific detail.

## Branches

- `main` — stable, deployable to production.
- `develop` — integration branch; feature branches merge here first.
- Feature branches: `feature/<short-description>` — all work happens on feature branches and merges to `develop` via PR.

Commits follow Conventional Commits: `feat:`, `fix:`, `refactor:`, `chore:`, `docs:`, `test:`.

## Environments

| Environment | Producer DB | Compute |
|---|---|---|
| `dev` | RDS Postgres single-AZ (small instance) | ECS dev task |
| `staging` | Aurora cluster (single region) | ECS, smaller capacity |
| `prod` | Aurora Global (writer `us-east-1`, reader `us-east-2`) | Multi-AZ Fargate with autoscaling |

Each environment maps to its own directory under `infra/environments/`.

## Infrastructure tooling

- **IaC:** Terraform
- **State backend:** S3 + DynamoDB lock table, naming pattern `cht-content-hub-terraform-state-*` and `cht-content-hub-terraform-locks`
- **CI/CD:** GitHub Actions with OIDC for AWS authentication (no long-lived keys)
- **Region:** `us-east-1` primary, `us-east-2` for production Aurora reader replica
- **Account:** `233636046512`

## Companion services

- **`cht-platform-tool`** — consumer side. Owns user identity, CME, platform admin. Pattern reference for Terraform layout (this repo follows the same structural conventions).
- **Live `mediahub.communityhealth.media`** — the EC2 monolith being replaced. Kept alive during the migration window; APIs only after the SPA cuts over to Content Hub.
