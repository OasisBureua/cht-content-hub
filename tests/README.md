# tests/

Cross-service tests.

- `integration/` — tests that exercise multiple services together against a real (dev) environment or a Docker Compose stack
- `e2e/` — full end-to-end user flow tests (e.g. log in via Cognito → fetch clip via API → verify tag application → verify CHT cache invalidation)

Unit tests for individual Lambdas live next to the Lambda (`services/lambdas/<function>/tests/`). Unit tests for the ECS API live in `services/api/tests/`. This top-level `tests/` directory is reserved for tests that span service boundaries.
