# scripts/

Local dev helpers and one-shot operational scripts.

Examples (to be populated):
- `local-dev-up.sh` — start a local Postgres + Cognito Local + the API in Docker Compose
- `invoke-lambda-local.sh` — invoke a Lambda locally via AWS SAM
- `dms-status.sh` — check DMS replication lag during migration
- `cognito-create-test-user.sh` — provision a test Cognito user in dev

Scripts should be idempotent and self-documenting (run with `--help` for usage).
