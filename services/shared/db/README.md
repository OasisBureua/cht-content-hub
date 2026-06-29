# services/shared/db/

Aurora connection management and ORM models.

- Connection pooling configured per execution context (long-lived for ECS API, single-connection per Lambda invocation)
- SQLAlchemy models defined here, not duplicated per service
- Migration tooling (Alembic) operates against the models defined in this package
- Secrets fetched from Secrets Manager; no DB credentials in environment variables
