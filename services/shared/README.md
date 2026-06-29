# services/shared/

Code reused across the ECS API and Lambdas.

Imported as a local Python package by `services/api/` and vendored into each Lambda's deployment package at build time. **Not** a runtime layer — keeps Lambda cold starts predictable and version drift impossible.

## Modules

- `db/` — Aurora connection management, SQLAlchemy ORM models, schema utilities
- `auth/` — Cognito JWT validation against JWKS, group-claim parsing, RBAC helpers
- `observability/` — structured JSON logging, CloudWatch metric helpers, distributed tracing utilities
- `types/` — Pydantic models and dataclasses used across services (request/response shapes, domain entities)
