# services/shared/

Code shared across the ECS API and Lambdas.

## Distribution

Two patterns:

- **Lambda Layer (`post_tagger`):** the foundational tagging logic is packaged as a versioned Lambda Layer. Any Lambda that runs `scan_text_for_tags` imports from the layer at runtime. Single source of truth, single deploy.
- **Vendored at build time (everything else):** `db/`, `auth/`, `cache/`, `observability/`, `types/` are vendored into each Lambda's deployment package at build time. Keeps cold starts predictable and avoids the operational overhead of versioned layers for code that changes more frequently.

The ECS API imports `services/shared/` as a local Python package — no layer/vendoring distinction there.

## Modules

- `db/` — producer Aurora connection, SQLAlchemy ORM models, schema utilities
- `auth/` — Cognito JWT validation against JWKS, group-claim parsing, RBAC helpers
- `cache/` — HMAC client for `POST /internal/cache/catalog/clear` on the consumer side
- `observability/` — structured JSON logging, CloudWatch metric helpers, distributed tracing
- `types/` — Pydantic models and dataclasses (request/response shapes, domain entities)
