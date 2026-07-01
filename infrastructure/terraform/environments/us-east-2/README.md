# us-east-2 — DR standby (Phase 3b)

Deploy after **us-east-1** primary is stable. Mirrors CHT `environments/us-east-2` pattern:

- Cross-region RDS read replica of `contenthub-{env}-db`
- Standby ECS tasks at ~50% capacity
- ECR image replication from us-east-1
- Secrets Manager replica regions

## Status

Scaffold only — copy `us-east-1` modules with:

- `dr_standby_scale_factor = 0.5`
- Data sources for primary RDS and secrets in us-east-1
- Internal ALB DNS for CHT `CONTENTHUB_BASE_URL_SECONDARY`

See [docs/engineering/architecture.md](../../../docs/engineering/architecture.md).

## Apply order

1. `../../scripts/deploy.sh us-east-1 apply`
2. Enable ECR replication module (TODO)
3. `../../scripts/deploy.sh us-east-2 apply`
4. DR drill
