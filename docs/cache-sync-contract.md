# Contract: CHT catalog cache & sync refresh

Defines Redis caching on **chm-backend only** and cache invalidation when Content Hub sync completes.

**When to implement:** Phase 4 (Content Hub platform move) — document now for Hub worker + CHT backend alignment.

**Owner:** Uche Aduakaa  
**Reviewer:** Adaze Oviawe  
**Approved:** June 16, 2026 at 08:28 PM EDT  
**Status:** Draft

---

## Principles

- **CHT-only cache** — no HTTP cache in contenthub-api; no FastAPI middleware
- **24h TTL** — safety net for populated keys
- **Refresh on sync** — clear catalog keys after successful worker sync (no version counters)
- **Never cache** — auth, payments, admin writes, HCP upsert responses

---

## Redis

| Item | Value |
| ---- | ----- |
| Cluster | Shared ElastiCache (prefixes `cht:*`) |
| TTL | `EX 86400` |

### Key patterns

| Key | Content |
| --- | ------- |
| `cht:catalog:tags` | Tags JSON |
| `cht:catalog:clips:{hash(params)}` | Clips list response |
| `cht:catalog:playlists:{hash(params)}` | Playlist tags |
| `cht:kol-network:{hash(params)}` | KOL list response |

`hash(params)` = stable hash of sorted query string.

---

## Sync refresh flow

```
contenthub-worker completes successful sync
    → POST https://<chm-backend>/internal/cache/catalog/clear
    → Header: Authorization: Bearer <INTERNAL_CACHE_SECRET>
    → chm-backend deletes keys matching cht:catalog:* and cht:kol-network:*
    → Next user request = cache miss → fetch contenthub-api → store 24h
```

### Internal endpoint (CHT)

```
POST /internal/cache/catalog/clear
Authorization: Bearer ${INTERNAL_CACHE_SECRET}
```

Response: `204 No Content`

**Security:** ALB rule or SG — not public internet; shared secret in Secrets Manager.

### Worker hook (Content Hub)

Call CHT clear endpoint **only after** sync transaction commits successfully. Do not call on failed sync.

---

## Implementation checklist

**CHT backend:**

- [ ] Redis client + cache wrapper on catalog/KOL services
- [ ] Internal clear endpoint + guard
- [ ] `INTERNAL_CACHE_SECRET` in Secrets Manager

**contenthub-worker:**

- [ ] `CHT_CACHE_CLEAR_URL` + secret env vars
- [ ] HTTP POST on sync success
- [ ] Log success/failure (non-blocking — TTL still expires stale data)

---

## Testing

| Scenario | Expected |
| -------- | -------- |
| Cache miss | Hub called; key set with 24h TTL |
| Cache hit | Hub not called |
| After sync clear | Next request cache miss; new clips visible |
| Failed sync | Cache **not** cleared |
| Invalid secret on clear | 401; cache unchanged |

---

## Related

- CHT platform roadmap — CHT-only cache strategy (CHT platform repo)
- [contenthub-migration-plan.md](./contenthub-migration-plan.md)
