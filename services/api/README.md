# services/api/

The producer FastAPI surface for Content Hub. Runs on ECS Fargate behind ALB + WAF.

## Responsibilities

- **`/api/public/*`** — consumer-facing catalog endpoints. Auth via `X-API-Key` header (server-side calls from `cht-platform-backend` only). Consolidated successor to MediaHub's `routers/public_api.py`.
- **`/api/admin/studio/*`** — CHM staff studio UI endpoints (tag editor, analytics, clips, conversations, render, hcp-intel admin, reports, knowledge base, integrations). Auth via Cognito session JWT with `chm-admin` or `chm-editor` group claims.
- Direct producer Aurora reads/writes for synchronous operations
- Invokes the cache-clear contract (`POST /internal/cache/catalog/clear` on `cht-platform-backend`) after writes that affect catalog data, via the `services/shared/cache/` HMAC client

## What does NOT live here

- **`/api/admin/platform/*`** — that's `cht-platform-backend`'s surface (users, CME, client_ids). The producer never serves platform admin routes.
- **`/webhook/sync`** — ops-console is being decommissioned. There is no webhook ingest into the producer.
- Long-running compute (transcription, rendering, ingest) — those are Lambdas in `../lambdas/`
- Scheduled work — that's EventBridge → Lambda, defined in `../lambdas/` and `../step_functions/`
- DB schema migrations — those live in `../../migrations/`

## Endpoint design principle

Consolidate related operations into fewer, parameter-driven endpoints rather than proliferating one endpoint per variation. Cognito group claims (`chm-admin`, `chm-editor`, `chm-viewer`) determine what each caller sees within a shared endpoint, not which endpoint they call.

See `../../docs/conventions/api-design.md` for the full convention.

## Layout

- `src/routers/` — FastAPI route handlers, one file per resource type
- `src/middleware/` — Cognito JWT validation, request logging, rate limiting
- `src/models/` — Pydantic request/response models (DB models live in `../shared/db/`)
- `src/main.py` — FastAPI app entry point
- `Dockerfile` — container image built by CI, pushed to ECR `cht-content-hub-api`
- `pyproject.toml` — Python dependencies
