# Serverless sync jobs

EventBridge Scheduler + Lambda (+ SQS for long jobs) replacing the ECS worker APScheduler.

## Job catalog (target)

| Job | Schedule | Executor | Cache clear |
|-----|----------|----------|-------------|
| `platform_sync` | 12h | SQS + Lambda | Yes |
| `platform_stats` | 12h | SQS + Lambda | Yes |
| `post_tagging` | 12h | Lambda | Yes |
| `playlist_doctor_tagger` | 04:30 UTC | Lambda | Yes |
| `ai_summaries` | 12h | SQS + Lambda | Yes |
| `metric_snapshots` | 12h | Lambda | No |
| `hcp_intel_poll` | 30m | SQS + Lambda | No |
| `cache_clear` | on-demand | Lambda | — |

**Do not migrate:** `shoot_tag_pipeline` (dormant), `kol_cache_warm` (drop).

## Round 1 Lambdas (Phase 1.5)

```
sync/
├── README.md
├── jobs/
│   ├── post_tagging/
│   │   └── handler.py
│   ├── playlist_doctor_tagger/
│   │   └── handler.py
│   └── cache_clear/
│       └── handler.py
└── shared/
    ├── db.py          # VPC RDS access via Secrets Manager
    └── cht_cache.py   # POST /internal/cache/catalog/clear
```

## Handler contract

1. Idempotent — safe to retry
2. Tagging jobs: `reserved_concurrency=1`
3. On successful writes → invoke `cache_clear` Lambda
4. DLQ per SQS queue; credentials from Secrets Manager
5. VPC access to producer DB via IAM role

See [cache-sync-contract.md](../docs/cache-sync-contract.md) and [contenthub-migration-plan.md](../docs/contenthub-migration-plan.md) §7.

## Local development

Until Lambdas land, run the transitional ECS worker:

```bash
cd worker && python start_workers.py
```

The worker calls job modules that will live under `backend/src/jobs/` once application code is added.
