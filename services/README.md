# services/

All application code, organized by deployment shape.

- `api/` — the producer FastAPI surface deployed to ECS Fargate. Owns `/api/public/*` (consumer-facing catalog) and `/api/admin/studio/*` (CHM staff studio UI).
- `lambdas/<function>/` — event-driven Lambdas, one directory per function, organized by function.
- `step_functions/` — Step Function state machine definitions for multi-step orchestration.
- `shared/` — code reused across the API and Lambdas. `post_tagger` distributes as a Lambda Layer; other modules vendor at build time.
