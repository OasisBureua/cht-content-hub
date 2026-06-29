# scripts/

Local dev helpers and one-shot operational scripts.

Examples (to be populated):
- `local-dev-up.sh` — start a local Postgres + Cognito Local + the API in Docker Compose
- `invoke-lambda-local.sh` — invoke a Lambda locally via AWS SAM
- `pg-dump-from-legacy.sh` — extract producer-owned tables from the legacy MediaHub EC2 Postgres
- `pg-restore-to-dev.sh` — restore extracted dump into dev RDS
- `cognito-create-test-user.sh` — provision a test Cognito user in dev

Scripts should be idempotent and self-documenting (`--help` for usage).
