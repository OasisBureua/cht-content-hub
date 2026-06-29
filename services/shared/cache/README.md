# services/shared/cache/

HMAC client for `POST /internal/cache/catalog/clear` on `cht-platform-backend`.

## Why this exists

`cht-platform-backend` caches catalog data in ElastiCache (`cht:catalog:*`). The architectural rule that `cht-platform-backend` never reads the producer DB directly means cache invalidation can't be a DB trigger — it has to be an explicit HTTP call from the producer after a write.

This module provides the HMAC-signed POST client. Any Lambda that writes catalog data imports and invokes it.

## Usage

```python
from shared.cache import invalidate_catalog

await invalidate_catalog(keys=["cht:catalog:clip:abc123", "cht:catalog:kol:*"])
```

## Configuration

- Endpoint: `https://contenthub.communityhealth.media/internal/cache/catalog/clear` (resolved from `INTERNAL_CACHE_ENDPOINT` env var)
- Shared secret: `INTERNAL_CACHE_SECRET` (Secrets Manager path `cht-content-hub/{env}/internal-cache-secret`)
- Algorithm: HMAC-SHA256 over `<timestamp>.<body>`, header `X-Signature: t=<ts>,s=<hex>`
- Retry: 3x exponential backoff; after exhaustion, log and emit a CloudWatch alarm but do not block the calling Lambda (cache will expire on its own TTL).

## Spec

Canonical contract spec at `docs/cache-sync-contract.md` (TBD — to be written if not already in `cht-platform-tool`).
