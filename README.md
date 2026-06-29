# ContentHub

AWS-native rebuild of MediaHub.

## Status

Initial scaffolding. Directory structure and placeholder READMEs only — no application code, no infrastructure-as-code yet.

## Repo structure

| Path | Purpose |
|---|---|
| `infra/` | All AWS infrastructure-as-code. Environment-specific config in `infra/environments/`, reusable modules in `infra/modules/`. |
| `services/api/` | The persistent FastAPI surface that runs on ECS Fargate. Public and admin API endpoints, behind ALB + WAF. |
| `services/lambdas/<domain>/<function>/` | Event-driven Lambdas, one directory per function, grouped by domain. |
| `services/step_functions/` | Step Function state machine definitions for multi-step orchestration. |
| `services/shared/` | Code shared across the API and Lambdas — DB connection, Cognito JWT validation, observability helpers, common types. |
| `migrations/` | Forward migrations for the Aurora schema. |
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

- `dev` — per-developer experimentation, cost-optimized.
- `staging` — pre-prod verification.
- `prod` — live traffic.

Each environment maps to its own directory under `infra/environments/`.
