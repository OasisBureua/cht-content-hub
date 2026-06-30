# infra/modules/database/rds/

Single-AZ RDS Postgres module for the dev producer environment.

## Inputs

- Instance identifier (`cht-content-hub-dev-postgres`)
- Instance class (`db.t3.small` default)
- Engine version (match Aurora prod)
- Allocated storage, storage type, encryption
- VPC + subnet group references

## Outputs

- Endpoint
- Port
- Master credentials secret ARN

## Notes

- Dev only. Prod uses `../aurora-global/`.
- Cost: ~$25/month for `db.t3.small` plus storage.
- Backups: 7-day retention, single-AZ.
