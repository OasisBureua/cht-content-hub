# migrations/

Producer Aurora schema migrations (forward-only). System-wide source of truth for the producer DB schema.

Tool: Alembic.

## Conventions

- One revision per logical schema change. No "fix typo in last migration" — squash before merge.
- Migration filenames include the timestamp and a short description: `2026_07_01_add_clip_render_state.py`
- Schema changes that span multiple services (e.g. renaming a column used by both the API and several Lambdas) are coordinated as a single migration with the corresponding code changes in the same PR.
- Migrations run as part of the deploy pipeline against staging first, prod second, with a manual approval gate.

## Initial population

Round 1 dev DB is populated by `pg_dump` from the legacy MediaHub EC2 Postgres, restored into the dev RDS instance. See the migration plan's section 8 for the procedure.

Pre-cutover schema state lives in the legacy MediaHub's own migration history. This directory only manages schema changes made *after* the producer DB is in service.
