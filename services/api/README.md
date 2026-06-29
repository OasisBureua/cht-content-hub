# services/api/

The persistent FastAPI surface for ContentHub. Runs on ECS Fargate behind ALB + WAF.

## Responsibilities

- Public API endpoints (consolidated successor to MediaHub's `routers/public_api.py`)
- Admin API endpoints (replacement for the editorial back-office surfaces in MediaHub)
- Cognito JWT validation on every authenticated route
- Direct Aurora reads/writes for synchronous operations
- Lambda invocation for async work (queues SQS messages or invokes Step Functions)

## What does NOT live here

- Long-running compute (transcription, rendering, ingest) — those are Lambdas in `../lambdas/`
- Scheduled work — that's EventBridge → Lambda, defined in `../lambdas/` and `../step_functions/`
- DB schema migrations — those live in `../../migrations/`

## Endpoint design principle

Consolidate related operations into fewer, parameter-driven endpoints rather than proliferating one endpoint per variation. Role-based access (Cognito groups) determines what each caller sees within a shared endpoint, rather than separate endpoints per role.

See `../../docs/conventions/api-design.md` for the full convention.

## Layout

- `src/routers/` — FastAPI route handlers, one file per domain or resource type
- `src/middleware/` — auth middleware, request logging, rate limiting
- `src/models/` — Pydantic request/response models (DB models live in `../shared/db/`)
- `src/main.py` — FastAPI app entry point
- `Dockerfile` — container image built by CI
- `pyproject.toml` — Python dependencies
