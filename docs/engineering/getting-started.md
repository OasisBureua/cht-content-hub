# Getting started

> **Status:** Infrastructure-first. Application code in `backend/` and `worker/` is not yet added.

## Prerequisites

- AWS CLI
- Terraform >= 1.0
- Docker Desktop (optional — local Postgres only)

## 1. Review migration plan

Start with [contenthub-migration-plan.md](../contenthub-migration-plan.md) — Phase 1 infra (CH-01) before any application code.

## 2. Optional local Postgres

For future app development:

```bash
docker compose up -d
```

Postgres on **localhost:5433**.

## 3. Terraform (primary path)

```bash
cp infrastructure/terraform/environments/variables/dev.tfvars.example \
   infrastructure/terraform/environments/variables/dev.tfvars
# Edit dev.tfvars with account-specific values

./scripts/deploy-primary.sh dev
```

See [infrastructure/README.md](../../infrastructure/README.md).

## After infra is decided

Application work resumes in this order:

1. `backend/` — FastAPI `contenthub-api` (`/api/public/*` first)
2. Data port — `./scripts/pg_dump_restore.sh`
3. `sync/` — EventBridge + Lambda (or skip ECS worker entirely)
4. `worker/` — only if bridging before Lambdas

CHT platform wiring: [cht-public-api-contract.md](../cht-public-api-contract.md)
