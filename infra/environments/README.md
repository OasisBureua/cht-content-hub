# infra/environments/

Per-environment IaC composition.

| Environment | Purpose | Data layer | Compute |
|---|---|---|---|
| `dev/` | Per-developer experimentation. Cost-optimized. | Small RDS Postgres (not Aurora). | Single-task ECS or local Docker for the FastAPI surface. |
| `staging/` | Pre-prod verification. Mirrors prod shape. | Aurora cluster (single region OK). | Same shape as prod, smaller capacity. |
| `prod/` | Live traffic. | Aurora Global with primary in `us-east-1`, reader in second region. | Multi-AZ Fargate with autoscaling. |

Each environment subdirectory composes modules from `../modules/` with environment-specific values (sizing, region, capacity, retention policies).
