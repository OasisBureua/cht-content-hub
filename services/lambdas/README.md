# services/lambdas/

Event-driven AWS Lambdas, organized by function. Each Lambda is a self-contained directory.

## Layout

```
lambdas/
├── tagging/        # post_tagger, playlist_doctor_tagger — content tagging
├── sync/           # per-platform sync: youtube, linkedin, x, facebook, instagram
├── video/          # transcription, video processing (post-R1)
├── hcp_intel/      # HCP intel orchestrator + ingests (post-R1)
└── cache_clear/    # POST /internal/cache/catalog/clear on cht-platform-backend
```

## Per-Lambda layout

Each Lambda is a self-contained directory:

```
<lambda_name>/
├── handler.py          # AWS Lambda entry point — minimal, calls into logic.py
├── logic.py            # Business logic, testable in isolation
├── pyproject.toml      # Lambda-specific dependencies (kept minimal)
├── README.md           # Purpose, trigger, inputs/outputs, runbook
└── tests/
    ├── test_logic.py
    └── fixtures/
```

The directory name maps to the AWS Lambda function name with the `cht-content-hub-` prefix added at deploy time (e.g. `tagging/post_tagger/` → `cht-content-hub-tagging-post-tagger`).

## Conventions

- **Idempotent handlers.** Every Lambda must be safe to retry.
- **Reserved concurrency = 1** on tagging Lambdas (avoid duplicate tag writes from overlapping invocations).
- **Lambda VPC role** for any Lambda that touches the producer DB. Egress through VPC NAT to reach external APIs.
- **Cache invalidation pattern:** any Lambda that writes catalog data invokes `cache_clear` after successful commit.
- **Shared code:** `post_tagger` distributes as a Lambda Layer (foundation). Other `services/shared/` modules are vendored into each Lambda's deployment package at build time.
- **Secrets** fetched from AWS Secrets Manager. No `.env` files.
- **Triggers:** EventBridge Scheduler for cron, SQS for queued/long jobs, direct invoke for fast per-event work. See `infra/modules/eventbridge/` and `infra/modules/sqs/`.

## What's NOT here

- **Reports.** Deferred entirely from Round 1. Domain disposition decided after R1 lands.
- **shoot_tag_pipeline.** Dormant per migration plan. Do not migrate.
- **auto_segmenter.** Zero callers, retired.
