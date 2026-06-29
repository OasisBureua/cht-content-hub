# migrations/

Aurora schema migrations (forward-only). System-wide source of truth for database schema.

Tool: Alembic, or equivalent. Whichever migration tool is used, this is where its versions live.

## Conventions

- One revision per logical schema change. No "fix typo in last migration" — squash before merge.
- Migration filenames include the timestamp and a short description: `2026_07_01_add_cognito_user_id_to_users.py`
- Schema changes that span multiple services (e.g. renaming a column used by both the API and several Lambdas) are coordinated as a single migration with the corresponding code changes in the same PR.
- Migrations run as part of the deploy pipeline against staging first, prod second, with a manual approval gate.

## DMS-mirrored data vs. forward migrations

During the migration phase, Aurora is initially populated by AWS DMS replicating from the live MediaHub Postgres. Forward migrations in this directory apply only to schema changes made *after* the DMS cutover.

Pre-cutover schema lives wherever MediaHub's existing migrations live (legacy repo). This directory does NOT manage that history.
