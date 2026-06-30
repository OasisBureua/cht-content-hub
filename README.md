# CHT Content Hub

**Community Health Technologies — Content Hub producer** (headless API + sync jobs) powering the clinical content catalog consumed by the CHT platform.

The consumer and admin SPA live in [cht-platform-tool](https://github.com/OasisBureua/cht-platform-tool). This repo owns producer infrastructure, sync jobs, and (later) the API surface.

> **Current focus:** infrastructure decisions before application code. `backend/` and `worker/` are placeholders.

---

## Project Structure

```
cht-content-hub/
├── infrastructure/   # Terraform IaC (AWS) — active
├── docs/             # Migration plan + engineering docs
├── sync/             # EventBridge / Lambda job definitions (planned)
├── scripts/          # Deploy & data migration helpers
├── backend/          # contenthub-api — TBD after infra
└── worker/           # ECS bridge or retired — TBD after infra
```

---

## Target architecture

| Component | Dev | Prod |
|-----------|-----|------|
| `contenthub-api` | ECS Fargate | ECS Fargate |
| Producer database | RDS Postgres | Aurora Global |
| Sync | EventBridge + Lambda (+ SQS) | Same |
| CHT integration | `X-API-Key` on `/api/public/*` | Same |

**Rule:** CHT platform never connects to the producer database — HTTP only.

| Host | Env | Producer API |
|------|-----|--------------|
| `devhub.communityhealth.media` | Dev | `MEDIAHUB_BASE_URL=https://devhub.communityhealth.media/api/public` |
| `contenthub.communityhealth.media` | Prod | `MEDIAHUB_BASE_URL=https://contenthub.communityhealth.media/api/public` |

See [docs/contenthub-migration-plan.md](docs/contenthub-migration-plan.md) for phased rollout.

---

## Getting started (infra)

### Prerequisites

- AWS CLI
- Terraform >= 1.0
- Docker Desktop (optional — local Postgres for future app dev)

### Local Postgres (optional, for future app work)

```bash
docker compose up -d
```

Postgres on **localhost:5433** (avoids conflict with CHT platform on 5432).

### Terraform

```bash
cp infrastructure/terraform/environments/variables/dev.tfvars.example \
   infrastructure/terraform/environments/variables/dev.tfvars
./scripts/deploy-primary.sh dev
```

See [infrastructure/README.md](infrastructure/README.md) and [docs/engineering/deployment.md](docs/engineering/deployment.md).

---

## Verification

```bash
./verify.sh
./scripts/verify-certificate.sh devhub
./scripts/smoke.sh https://devhub.communityhealth.media
```

---

## Docs

| File | Description |
|------|-------------|
| [docs/contenthub-migration-plan.md](docs/contenthub-migration-plan.md) | Canonical migration runbook |
| [docs/contenthub-admin-architecture.md](docs/contenthub-admin-architecture.md) | Admin routes & Cognito groups |
| [infrastructure/README.md](infrastructure/README.md) | Terraform layout |
| [docs/engineering/architecture.md](docs/engineering/architecture.md) | System design |
