# Content Hub — Campaign & Report API Contract

**Status:** Draft (Hub implementation + CHT proxy)  
**Audience:** Content Hub backend, CHT platform backend, CHT admin UI  
**UI source:** `frontend/src/pages/admin/content-hub/lib/store.ts` + `types.ts` (CHT repo)  
**Hub implementation:** `backend/src/admin/router.py`, `backend/src/services/campaign_*.py`, `backend/src/services/platform_data.py`

---

## Architecture

```
CHT Admin UI (/admin/content-hub)
    → CHT NestJS  /api/admin/content-hub/*
        ├─→ Content Hub  (pull campaign + platform snapshots at report time)
        ├─→ Content Hub  POST .../report/generate
        └─→ HubSpot API  (CHT only — on manual HubSpot sync, not every report view)

Content Hub (background + storage)
    ├─ On-demand: POST .../campaigns/{id}/platforms/{platform}/sync
    └─ Postgres: campaign_platform_data + hubspot_raw_data on campaign
    (Daily resync is not running. next_sync_at is stored; no job reads it.)
```

### Ownership

| Concern | Owner |
|---|---|
| Campaign CRUD, templates | Content Hub |
| LinkedIn Ads and YouTube metrics | Content Hub API connectors, stored in `campaign_platform_data` |
| Platform connector credentials (non-HubSpot) | Content Hub (`integration_settings`) |
| Daily platform resync | Not built. `next_sync_at` is stored; no job reads it. |
| Manual platform refresh | Content Hub (`POST .../sync`) |
| Report orchestration | CHT (pull from Hub → `POST .../report/generate`) |
| Analytics report builder | Content Hub `campaign_reports.py`, from stored rows. Not `POST /api/reports`. |
| HubSpot token + API | CHT only |
| HubSpot snapshot on campaign | CHT PATCHes `hubspotSyncedAt` + `hubspotRawData` |

**Rule:** If it is not HubSpot, Content Hub owns the data lifecycle. CHT never stores platform metric rows long-term.

### Fresh data vs reports

| Action | What happens |
|---|---|
| Admin clicks Sync / Refresh | Hub pulls from platform → updates `campaign_platform_data`. HubSpot sync via CHT → PATCH campaign. |
| Admin opens report | CHT reads stored state from Hub → `POST .../report/generate`. No live platform calls. |
| Daily resync | Not running. `next_sync_at` is stored on `campaign_platform_data`; no job reads it. |

---

## Auth

| Caller | Header |
|---|---|
| CHT → Content Hub admin | `Authorization: Bearer <access_token>` with scope `hub/admin.{crud}` (`hub/admin.*` is also accepted). `X-API-Key` is not accepted. |
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
- `POST /campaigns/{id}/platforms/{platform}/sync` — on-demand pull (LinkedIn Ads + YouTube when `enabled: true` and not `stub`)
- `POST /campaigns/{id}/sync-all`

### CSV bootstrap (fallback)
- `GET/POST /campaigns/{id}/uploads` — ingests into `campaign_platform_data`

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

### Not this admin API
Hub does not serve `POST /api/reports`. The generate-time warehouse packet is a different route, `GET /api/campaigns/{id}/report-packet`, authorized with `hub/reports.{crud}`. `POST /campaigns/{id}/report/generate` above is the older CHT analytics report built from stored snapshots. It is not that packet and not `POST /api/reports`.

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
- [x] `campaign_platform_data` + CSV → snapshot ingest
- [x] `GET .../platform-data`, `GET .../validation`
- [x] `POST .../report/generate` reads stored `campaign_platform_data` and `hubspot_raw_data`
- [x] `GET/PATCH /integrations` (stub sync via `stub: true` config)
- [x] CHT proxy: `AdminContentHubController` at `admin/content-hub`, client `frontend/src/pages/admin/content-hub/lib/store.ts`

### Phase 2 — Sync engine
- [x] LinkedIn Ads and YouTube connectors (`services/connectors/linkedin_ads.py`, `services/connectors/youtube.py`)
- [ ] Meta API sync (CSV upload only; `_fetch_connector_rows` rejects other platforms)
- [ ] Daily cron resync (`next_sync_at` is stored; no job reads it)
- [x] `campaign_reports.py` builds the analytics and executive reports from stored rows

### Phase 3 — Polish
- [ ] AI insights (`POST .../insights` returns a placeholder string, not a model)
- [ ] Executive config PATCH, templates UX
- [ ] UI: Upload → Sync where connectors exist

---

## CHT checklist

1. `ContentHubCampaignService` — Hub campaign calls from CHT
2. `AdminContentHubController` — `@Controller('admin/content-hub')` (this class exists)
3. Report: `GET .../report` → Hub GET campaign + platform-data → Hub POST report/generate
4. HubSpot status + sync → PATCH Hub campaign
5. Redis: cache campaign lists only; invalidate on writes
6. Frontend: replace `store.ts`; sync buttons → Hub sync endpoints

See full field-level contract in team doc / PR description when cutting over UI.
