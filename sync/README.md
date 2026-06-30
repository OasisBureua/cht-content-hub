# Serverless sync jobs

EventBridge + Lambda (+ SQS for long jobs) — **same pattern in dev and prod**.

Each environment gets its **own** Lambda functions, queues, and schedules. Dev and prod share:

- Handler code (`sync/jobs/*`)
- Business logic (`backend/src/hcp_intel/*`)
- Deployment artifact (`dist/sync-lambda.zip` from `./scripts/build-sync-lambda.sh`)
- Terraform module (`modules/compute/lambda-job/`)

## Job catalog

| Job | Schedule | Trigger | Default enabled |
|-----|----------|---------|-----------------|
| `hcp_intel_poll` | every 30m | EventBridge → SQS → Lambda | yes |
| `openalex_backfill` | Sun 03:30 UTC | EventBridge → Lambda | yes |
| `kol_hcp_matcher` | daily 04:00 UTC | EventBridge → Lambda | yes |
| `cache_clear` | on-demand | Lambda invoke | yes |
| `post_tagging` | every 12h | EventBridge → Lambda | no (catalog not on Hub yet) |
| `playlist_doctor_tagger` | 04:30 UTC | EventBridge → Lambda | no |

**Do not migrate:** `kol_cache_warm` (CHT owns Redis).

## Build & deploy

```bash
# 1. Package (same zip for dev + prod)
./scripts/build-sync-lambda.sh $(git rev-parse --short HEAD)

# 2. Terraform apply (creates contenthub-dev-sync-* or contenthub-prod-sync-*)
./scripts/deploy-primary.sh dev apply
```

Optional tfvars overrides:

```hcl
sync_jobs_enabled = {
  post_tagging             = false
  playlist_doctor_tagger   = false
}
```

Manual invoke (dev example):

```bash
aws lambda invoke --function-name contenthub-dev-sync-kol-hcp-matcher \
  --payload '{}' /tmp/out.json && cat /tmp/out.json
```

## Handler contract

1. Idempotent — safe to retry
2. Serial jobs: `reserved_concurrent_executions = 1`
3. VPC access to producer RDS via Secrets Manager (`DATABASE_SECRET_ARN`)
4. Optional CHT cache clear via `CHT_CACHE_CLEAR_URL` + `INTERNAL_CACHE_SECRET`

See [cache-sync-contract.md](../docs/cache-sync-contract.md) and [contenthub-migration-plan.md](../docs/contenthub-migration-plan.md).

## Layout

```
sync/
├── requirements.txt          # Lambda runtime deps
├── jobs/
│   ├── hcp_intel_poll/
│   ├── openalex_backfill/
│   ├── kol_hcp_matcher/
│   └── cache_clear/
└── shared/
    ├── runtime.py            # path setup + asyncio.run
    ├── secrets.py            # Secrets Manager → DATABASE_URL
    └── cht_cache.py
```

Business logic lives in `backend/src/hcp_intel/` (shared with `contenthub-api`).
