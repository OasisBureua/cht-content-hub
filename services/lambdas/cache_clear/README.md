# services/lambdas/cache_clear/

Posts to `cht-platform-backend`'s `/internal/cache/catalog/clear` endpoint to evict the consumer-side catalog cache after producer-side writes.

## Why this exists

`cht-platform-backend` caches catalog data in its own ElastiCache (`cht:catalog:*`). When producer Lambdas write new or updated clip/tag/playlist data, that cache needs to be invalidated or the consumer serves stale data.

Per the architectural rule: `cht-platform-backend` never reads the producer DB directly. So invalidation can't be a DB trigger or pub/sub off the producer DB. It's an HTTP call from the producer Lambda to a defined endpoint on the consumer.

## Contract

- **Method:** POST
- **URL:** `https://contenthub.communityhealth.media/internal/cache/catalog/clear`
- **Auth:** HMAC-SHA256 signature with shared secret `INTERNAL_CACHE_SECRET` (Secrets Manager)
- **Payload:** JSON `{"keys": ["cht:catalog:clip:*", "cht:catalog:kol:*"]}` — keys can be exact or pattern
- **Response:** 204 No Content on success
- **Retry:** 3x with exponential backoff. After exhaustion, alarm but do not block the calling Lambda — the cache will expire on its own TTL.

## Implementation

The signing logic lives in `services/shared/cache/` and is imported by any Lambda that writes catalog data. This Lambda directory is the standalone wrapper for orchestrated cache invalidations (e.g. after a batch import).

## Spec source

`docs/cache-sync-contract.md` (canonical contract, lives in `cht-platform-tool` if it owns the receiving endpoint, or here if we own the spec).
