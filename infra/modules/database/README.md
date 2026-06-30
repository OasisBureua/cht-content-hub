# infra/modules/database/

Producer database modules.

- `rds/` — single-AZ RDS Postgres for the dev environment
- `aurora-global/` — Aurora Global cluster for production (writer `us-east-1`, reader `us-east-2`)
