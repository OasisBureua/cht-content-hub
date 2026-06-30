# infra/modules/database/aurora-global/

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

- Dev uses `../rds/` instead.
- Master credentials rotation: enabled, default 30 days via Secrets Manager.
