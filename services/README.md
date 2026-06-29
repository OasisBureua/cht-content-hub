# services/

All application code, organized by deployment shape.

- `api/` — the persistent FastAPI surface deployed to ECS Fargate. Hosts the public API (consolidated, role-gated successor to MediaHub's `public_api.py`) and the admin API. The only thing external traffic ever talks to.
- `lambdas/<domain>/<function>/` — event-driven Lambdas, one directory per function, grouped by domain.
- `step_functions/` — Step Function state machine definitions for multi-step orchestration. Lambdas live in `lambdas/`; their orchestration definitions live here.
- `shared/` — code reused across the API and Lambdas. Vendored into each Lambda at build time, not a runtime dependency.
