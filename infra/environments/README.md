# infra/environments/

Per-environment Terraform composition.

| Environment | Producer DB | Compute | Notes |
|---|---|---|---|
| `dev/` | RDS Postgres single-AZ (`db.t3.small` or similar) | ECS Fargate, single task | Cost-optimized. Aurora overkill for dev. |
| `staging/` | Aurora cluster, single region (`us-east-1`) | ECS Fargate, smaller capacity than prod | Mirrors prod shape for pre-prod verification. |
| `prod/` | Aurora Global — writer `us-east-1`, reader `us-east-2` | Multi-AZ Fargate with autoscaling | Production traffic. DR via reader region. |

Each environment subdirectory composes modules from `../modules/` with environment-specific values.
