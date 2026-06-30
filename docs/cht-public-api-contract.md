# CHT ↔ MediaHub public API contract

**Scope:** Endpoints CHT actively calls. This is the **extraction boundary** for `mediahub-api` on ECS — everything else in `backend/legacy/` is out of scope for the CHT producer microservice (EC2 admin, webhooks, post-MVP).

**Base URL (prod):** `https://contenthub.communityhealth.media/api/public`  
**Base URL (dev):** `https://devhub.communityhealth.media/api/public`  
**Auth:** Header `X-API-Key: <PUBLIC_API_KEY>` on all routes below (except where noted).

**Implementation:** `backend/src/public/router.py` with schemas in `backend/src/schemas/public.py`, helpers in `backend/src/utils/public.py`. Domain models in `backend/src/models/`. Legacy shims at `legacy/routers/public_api.py` for EC2 monolith.

---

## Read endpoints (11 usages · 10 distinct paths)

| # | Method | Path | CHT usage | MediaHub handler |
|---|--------|------|-----------|------------------|
| 1 | GET | `/tags` | Tag facets for catalog filters | `get_public_tags` |
| 2 | GET | `/clips` | Video catalog (list) | `get_public_clips` |
| 3 | GET | `/clips/{id}` | Clip detail | `get_public_clip` |
| 4 | GET | `/playlists` | Curator playlist tag overlay | `get_public_playlists` |
| 5 | GET | `/doctors` | Doctor directory | `get_public_doctors` |
| 6 | GET | `/doctors/{slug}` | Doctor profile + clips | `get_public_doctor` |
| 7 | GET | `/transcripts/{shoot_id}` | Diarized transcript | `get_public_transcript` |
| 8 | GET | `/kols` | KOL network list | `get_public_kols` |
| 9 | GET | `/kols/{slug}` | KOL profile | `get_public_kol` |
| 10 | GET | `/kols/{slug}/publications` | OpenAlex publications | `get_public_kol_publications` |
| 11 | GET | `/clips?q=…` | **Search** (same path as #2) | `get_public_clips` with `q` param |

**Search:** CHT `MediaHubService.search()` calls `GET /clips?q=…` — not `GET /search`. MediaHub also exposes `/search` for legacy callers; CHT does not use it.

**Full URLs (prod example):**

```http
GET  https://contenthub.communityhealth.media/api/public/tags
GET  https://contenthub.communityhealth.media/api/public/clips
GET  https://contenthub.communityhealth.media/api/public/clips/{id}
GET  https://contenthub.communityhealth.media/api/public/clips?q=her2
GET  https://contenthub.communityhealth.media/api/public/playlists
GET  https://contenthub.communityhealth.media/api/public/doctors
GET  https://contenthub.communityhealth.media/api/public/doctors/{slug}
GET  https://contenthub.communityhealth.media/api/public/transcripts/{shoot_id}
GET  https://contenthub.communityhealth.media/api/public/kols
GET  https://contenthub.communityhealth.media/api/public/kols/{slug}
GET  https://contenthub.communityhealth.media/api/public/kols/{slug}/publications
```

---

## Write endpoint (1)

| Method | Path | CHT usage | MediaHub handler |
|--------|------|-----------|------------------|
| POST | `/hcp/upsert` | Sync HCP roster from CHT registration | `hcp_upsert` |

```http
POST https://contenthub.communityhealth.media/api/public/hcp/upsert
Content-Type: application/json
X-API-Key: <PUBLIC_API_KEY>
```

CHT callers: `backend/src/modules/outbound-sync/mediahub-sync.service.ts`, `backfill-outbound-sync.ts`.

---

## Supporting services (shared domain, not separate HTTP)

These modules back the public routes — live in `backend/src/`:

| Area | Legacy modules |
|------|----------------|
| Catalog / clips | `models/clip`, `post`, `shoot`, `playlist_tag`; `services/kol_regions.py` |
| Doctors | `models/kol`, KOL slug map in `src/public/router.py` |
| KOL network | `models/kol`, `hcp_intel/models.py` (`HCPSignal` for publications) |
| Transcripts | `models/shoot`, transcript fields on shoot/conversation |
| HCP upsert | `services/hcp_upsert.py` (API) + worker `hcp_intel_*` jobs for enrichment |
| Summaries | `services/ai_descriptions.py` — Claude Haiku (`ANTHROPIC_API_KEY`) |
| Tagging | `services/post_tagger.py` — keyword vocabulary (worker `post_tagging` job) |

**Worker (producer):** Keeps all platform sync + HCP intel jobs that **populate** the data these endpoints read — see [mediahub-services.md](./mediahub-services.md).

---

## On MediaHub but not in CHT contract

| Route | Notes |
|-------|--------|
| `GET /api/public/shoots` | Defined in `src/public/router.py`; CHT client has `getShoots()` but **no controller calls it** |
| `GET /api/public/search` | Legacy alias; CHT uses `/clips?q=` |
| `POST /api/public/kb/correct-transcript` | n8n / KB workflow — not CHT catalog |
| `GET /api/public/debug/recent-errors` | Ops debug |
| `GET /api/public/status` | `src/public/status.py` — monitoring; optional for CHT smoke tests |
| `POST /webhook/sync` | ops-console — separate contract ([WEBHOOK_API.md](./WEBHOOK_API.md)) |

Do **not** drop these until callers are confirmed retired; they are simply **outside the CHT extraction slice**.

---

## ECS dev smoke (CHT)

After deploy, CHT dev should validate at minimum:

```bash
curl -s -H "X-API-Key: $KEY" "$BASE/tags" | head
curl -s -H "X-API-Key: $KEY" "$BASE/clips?limit=1"
curl -s -H "X-API-Key: $KEY" "$BASE/kols?limit=1"
curl -s -o /dev/null -w "%{http_code}" "$BASE/../status"   # optional
```

---

## Future path migration

Planned rename: `/api/public/*` → `/api/*` with unchanged shapes. CHT `MEDIAHUB_BASE_URL` drops `/public` segment when both sides cut over.

---

## Related

- CHT client: `cht-platform-tool/backend/src/modules/catalog/mediahub.service.ts`
- CHT KOL: `cht-platform-tool/backend/src/modules/kol-network/`
- [mediahub-architecture.md](./mediahub-architecture.md)
- [cache-sync-contract.md](./cache-sync-contract.md)
