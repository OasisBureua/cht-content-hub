# services/shared/db/

Producer Aurora connection management and ORM models.

- Connection pooling configured per execution context (long-lived for ECS API, single-connection per Lambda invocation)
- SQLAlchemy models defined here, not duplicated per service
- Alembic migrations in `migrations/` operate against the models defined here
- Secrets fetched from Secrets Manager (path `cht-content-hub/{env}/db/credentials`)
- No Redis on the producer side. Transient state lives in DynamoDB (job records, idempotency keys) or doesn't exist (the legacy `redis_store` pattern is retired — `cht-platform-backend` keeps its own ElastiCache for consumer-side caching, the producer doesn't share it).
