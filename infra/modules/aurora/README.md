# infra/modules/aurora/

Aurora Global cluster module (production only).

## Inputs

- Cluster identifier (`cht-content-hub-prod-aurora`)
- Engine version (PostgreSQL — match the version Alembic targets in `migrations/`)
- Instance class (start `db.r6g.large` or smaller, scale up as needed)
- Primary region (`us-east-1`)
- Reader region (`us-east-2`)
- Backup retention, KMS key
- VPC + subnet group references

## Outputs

- Cluster endpoint (writer)
- Reader endpoint
- Cluster ARN
- Master credentials secret ARN in Secrets Manager

## Notes

- Dev environment uses `infra/modules/rds/` instead — Aurora Global is overkill for a single developer's test DB.
- Staging may use a single-region Aurora cluster (not Global) — TBD based on cost vs. realism trade.
- Master credentials rotation: enabled, default 30 days via Secrets Manager.
