# Content Hub — Campaign & Report API Contract

**Status:** Draft (Hub implementation + CHT proxy)  
**Audience:** Content Hub backend, CHT platform backend, CHT admin UI  
**UI source:** `frontend/src/pages/admin/content-hub/lib/store.ts` + `types.ts` (CHT repo)  
**Hub implementation:** `backend/src/admin/router.py`, `backend/src/services/campaign_*.py`, `platform_snapshots.py`

---

## Architecture

```
CHT Admin UI (/admin/content-hub)
    → CHT NestJS  /api/admin/content-hub/*
        ├─→ Content Hub  (pull campaign + platform snapshots at report time)
        ├─→ Content Hub  POST .../report/generate
        └─→ HubSpot API  (CHT only — on manual HubSpot sync, not every report view)

Content Hub (background + storage)
    ├─ Daily cron: resync platform data per active campaign (Phase 2)
    ├─ On-demand: POST .../campaigns/{id}/platforms/{platform}/sync
    └─ Postgres: campaign_platform_snapshots + hubspot_raw_data on campaign
```

### Ownership

| Concern | Owner |
|---|---|
| Campaign CRUD, templates | Content Hub |
| LinkedIn / Meta / YouTube / livestream / survey data | Content Hub (normalized snapshots) |
| Platform connector credentials (non-HubSpot) | Content Hub (`integration_settings`) |
| Daily platform resync | Content Hub (Phase 2 scheduler) |
| Manual platform refresh | Content Hub (`POST .../sync`) |
| Report orchestration | CHT (pull from Hub → `POST .../report/generate`) |
| Report builder logic | Content Hub (port from CHT `reports.ts`) |
| HubSpot token + API | CHT only |
| HubSpot snapshot on campaign | CHT PATCHes `hubspotSyncedAt` + `hubspotRawData` |

**Rule:** If it is not HubSpot, Content Hub owns the data lifecycle. CHT never stores platform metric rows long-term.

### Fresh data vs reports

| Action | What happens |
|---|---|
| Admin clicks Sync / Refresh | Hub pulls from platform → updates `campaign_platform_snapshots`. HubSpot sync via CHT → PATCH campaign. |
| Admin opens report | CHT reads stored state from Hub → `POST .../report/generate`. No live platform calls. |
| Daily cron (Phase 2) | Hub refreshes snapshots automatically. |

---

## Auth

| Caller | Header |
|---|---|
| CHT → Content Hub | `X-API-Key: ${CONTENTHUB_API_KEY}`, `X-Request-Id: <uuid>` |
| Browser → CHT | Session / admin JWT |

After Hub writes: `POST /api/internal/cache/clear?scope=contenthub` on CHT.

## Base URLs

| Environment | Content Hub | CHT proxy |
|---|---|---|
| Dev | `https://devhub.communityhealth.media/api/admin` | `https://<dev-domain>/api/admin/content-hub` |
| Prod | `https://contenthub.communityhealth.media/api/admin` | `https://<prod-domain>/api/admin/content-hub` |

---

## Hub routes (implemented / planned)

### Campaigns
- `GET/POST /campaigns`, `GET/PATCH/DELETE /campaigns/{id}`

### Platform data
- `GET /campaigns/{id}/platform-data` — sync status per platform
- `POST /campaigns/{id}/platforms/{platform}/sync` — on-demand pull (stub until Phase 2 connectors)
- `POST /campaigns/{id}/sync-all`

### CSV bootstrap (fallback)
- `GET/POST /campaigns/{id}/uploads` — ingests into `campaign_platform_snapshots`

### Validation & insights
- `GET /campaigns/{id}/validation`
- `POST /campaigns/{id}/insights`

### Reports (CHT server-to-server)
- `POST /campaigns/{id}/report/generate`
- `POST /campaigns/{id}/executive-report/generate`

Browser-facing (CHT only):
- `GET /api/admin/content-hub/campaigns/:id/report` → CHT orchestrates steps above

### Integrations (Hub — non-HubSpot)
- `GET/PATCH /integrations`

HubSpot (CHT only):
- `GET /api/admin/content-hub/integrations/hubspot/status`
- `POST /api/admin/content-hub/campaigns/:id/hubspot/sync` → PATCH Hub campaign

### Templates
- `GET/POST /templates`, `DELETE /templates/{id}`

---

## Database (Hub)

| Table | Notes |
|---|---|
| `campaigns` | Metadata + `executive_report_data`, `hubspot_raw_data`, `hubspot_synced_at` |
| `campaign_platform_data` | One row per `(campaign_id, platform, fetch_date UTC)` — same-day upsert |
| `platform_sync_runs` | Audit log per sync attempt |
| `integration_settings` | Non-HubSpot connector config |
| `report_templates` | Template metadata |

Migration: `0006_campaign_platform_data` (consolidates csv_uploads + snapshots)

**Daily bucket rule:** refresh on the same UTC calendar day updates the row; a new day inserts a new row. Reports read the latest `fetch_date` per platform.

---

## Implementation phases

### Phase 1 — MVP (this repo, in progress)
- [x] CRUD campaigns
- [x] `campaign_platform_snapshots` + CSV → snapshot ingest
- [x] `GET .../platform-data`, `GET .../validation`
- [x] `POST .../report/generate` (placeholder builder)
- [x] `GET/PATCH /integrations` (stub sync via `stub: true` config)
- [ ] Deploy + migrations on dev
- [ ] CHT proxy + store.ts swap

### Phase 2 — Sync engine
- [ ] Real per-platform connectors (LinkedIn first)
- [ ] Daily cron resync
- [ ] Port `reports.ts` into `campaign_reports.py`

### Phase 3 — Polish
- [ ] AI insights, executive config PATCH, templates UX
- [ ] UI: Upload → Sync where connectors exist

---

## CHT checklist

1. `ContentHubReportsService` — proxy + report orchestration
2. `AdminContentHubController` — `@Controller('admin/content-hub')`
3. Report: `GET .../report` → Hub GET campaign + platform-data → Hub POST report/generate
4. HubSpot status + sync → PATCH Hub campaign
5. Redis: cache campaign lists only; invalidate on writes
6. Frontend: replace `store.ts`; sync buttons → Hub sync endpoints

See full field-level contract in team doc / PR description when cutting over UI.
