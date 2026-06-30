# Data migration runbooks

| Runbook | Description |
|---------|-------------|
| [../contenthub-migration-plan.md](../contenthub-migration-plan.md) §8 | Round 1 pg_dump / restore procedure |
| [../scripts/pg_dump_restore.sh](../scripts/pg_dump_restore.sh) | Helper script for dump / restore / validate |

## Round 1 tables

`clips`, `posts`, `shoots`, `kols`, `kol_groups`, `kol_group_members`, `playlist_tags`, `hcps`, `hcp_signals`, `tag_audit`, `tag_proposal`, tag vocabulary tables.

Exclude: `users`, `client_users`, auth PII.
