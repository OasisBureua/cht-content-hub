# infra/modules/security/secrets-manager/

Secrets Manager secrets used by the producer.

Path convention: `cht-content-hub/{env}/{service}/{key}` (e.g. `cht-content-hub/dev/db/credentials`, `cht-content-hub/prod/internal-cache-secret`).

Rotation: enabled where supported (DB credentials default 30 days). Static secrets (cross-service HMAC, third-party API keys) rotated manually as needed.
