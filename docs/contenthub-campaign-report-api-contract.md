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
    └─ Postgres: posts + post_campaign_links + post_metrics_daily (YouTube),
       campaign_platform_data (LinkedIn Ads, CSV uploads), hubspot_raw_data on campaign
    └─ Daily: platform_metrics_sync Lambda (CPR-15, off by default)
```

### Ownership

| Concern | Owner |
|---|---|
| Campaign CRUD, templates | Content Hub |
| YouTube metrics | Content Hub: channel uploads in `posts`, daily counts in `post_metrics_daily`, linked to campaigns in `post_campaign_links` (CPR-15) |
| LinkedIn Ads metrics | Content Hub API connector, stored in `campaign_platform_data` |
| Platform connector credentials (non-HubSpot) | Content Hub (`integration_settings`) |
| Daily platform resync | Content Hub `platform_metrics_sync` Lambda (CPR-15). Off by default; enable with `sync_jobs_enabled.platform_metrics_sync`. |
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
| Daily resync | When enabled, `platform_metrics_sync` stores every YouTube upload's counts for the UTC day, relinks posts to campaigns, and stores one LinkedIn Ads snapshot per mapped campaign. |

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
- `GET/PUT /campaigns/{id}/kols` — KOLs attached to the campaign. PUT body `{"kolIds": [...]}` replaces the set; unknown ids return 422. Attached KOLs are added to the report packet's `kols`.

### Platform data
- `GET /campaigns/{id}/platform-data` — sync status per platform
- `POST /campaigns/{id}/platforms/{platform}/sync` — on-demand pull. YouTube: relinks, then refreshes the campaign's linked videos. LinkedIn Ads when `enabled: true` and not `stub`. 400 when the campaign has no linked YouTube posts or no LinkedIn mapping, 404 when they return no data, 502 when the platform call fails. Every attempt is logged in `platform_sync_runs` (`success`, `unmapped`, `no_data`, `not_enabled`, `error`).
- `POST /campaigns/{id}/sync-all`

### CSV bootstrap (fallback)
- `GET/POST /campaigns/{id}/uploads` — ingests into `campaign_platform_data`

### Validation & insights
- `GET /campaigns/{id}/validation`
- `POST /campaigns/{id}/insights`

### Reports (CHT server-to-server)
- `POST /campaigns/{id}/report/generate`
- `POST /campaigns/{id}/executive-report/generate`
- `GET /campaigns/{id}/report-inputs` — Generate card preview (CPR-51). Optional query: `windowStart`, `windowEnd` (ISO dates) and repeated `sources` (omitted means all sections). Built from the same packet as `GET /api/campaigns/{id}/report-packet`, so preview and report agree. Returns `campaignId`, `windowStart`, `windowEnd`, `sources`, `inputCompleteness`, `registeredCount`, `attendedCount` and `attendeesWithProfile` (attendees with a specialty or institution); the three counts are null when attendance is off. `inputCompleteness` maps each source to `fetchedAt`, `rowCount` and `status` (`ok`, `missing`, `error`), using the packet's keys: `template` is always present, and `transcripts` is added when sessions are requested. The `transcripts` entry counts sessions with transcript text or a stored transcript key; transcripts are not downloaded, so an unreadable stored key still counts. 404 for an unknown campaign.

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
| `campaign_kols` | `(campaign_id, kol_id)` KOLs attached by an admin (`0029_campaign_kols`) |

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
- [x] Daily resync: `platform_metrics_sync` Lambda (CPR-15), off by default
- [x] `campaign_reports.py` builds the analytics and executive reports from stored rows

### Social posts (CPR-15)

Every social post the Hub knows is a `posts` row. A campaign's YouTube numbers come from the posts linked to it.

- **YouTube sync:** Data API v3 with `YOUTUBE_API_KEY`. The daily job lists every upload on the channels in `YOUTUBE_CHANNEL_IDS` (default: CHM's official channel and the five branded channels), every YouTube post already in the Hub, and every video in a shoot's playlist. It upserts them into `posts` (new rows: source `youtube_api`) and stores the day's lifetime views, likes and comments in `post_metrics_daily` (source `youtube`, basis `lifetime_snapshot`). The legacy `posts` counts are kept current for the public clips API. A video in a shoot playlist gets that shoot when it has none. About 60 quota units a day of the 10,000 default. Watch time and retention need the YouTube Analytics API with a channel-owner login, which is not used.
- **Links:** `post_campaign_links` (post, campaign, Platform program when the campaign has one, CHM Content ID, method, confidence, status `active` / `suggested` / `removed`, created/removed by and at). The linker (`services/post_links.py`) runs after each daily sync and on Sync. Rules, strongest first: `campaign_map` (`campaignMap[campaign].youtubeVideoIds`), `content_id` (a v1.1 CHM Content ID in the post's title, description or URL that appears in exactly one campaign's tags, name or program name), `wordpress_embed` (the same, in a WordPress article that embeds the video), `shoot` (the post's shoot is mapped to the campaign), `promoted_post` (an ad takes the links of the post it promotes). Manual links are never changed or revived, and a link a person removed stays removed. An automatic link that no rule supports any more is marked removed by `linker`.
- **Reads:** platform-data, the analytics report and the report packet build the YouTube snapshot from the campaign's linked posts: each post's latest metrics row inside the window, one row per video (`video id`, `title`, `published`, `url`, `views`, `likes`, `comments`, `duration`). A YouTube CSV upload is used instead only when it is newer.
- **Sync now** (`POST .../platforms/youtube/sync`): relinks, then refreshes the campaign's linked videos. New uploads arrive with the daily sync.
- **Sync runs:** source-wide syncs are logged in `platform_sync_runs` with no campaign.

### LinkedIn Ads connector (CPR-15)

LinkedIn Ads reads only the ad campaigns a Hub campaign is mapped to; there is no account-wide fallback.

- **Mapping:** `PATCH /integrations` with `{"platforms": {"linkedin": {"enabled": true, "campaignMap": {"<hubCampaignId>": {"linkedinCampaignIds": ["..."]}}}}}`. The patch merges top-level keys only, so send the whole `campaignMap`.
- **LinkedIn Ads:** `/rest/adAnalytics` with `LINKEDIN_ADS_API_VERSION` (default `202610`; each version is supported for at least a year). Daily metrics per mapped ad campaign: impressions, clicks, landing page clicks, engagements, reactions, comments, shares, follows, video starts/views/completions, dwell time, cost.
- **LinkedIn credentials:** set `LINKEDIN_ADS_REFRESH_TOKEN` with `LINKEDIN_ADS_CLIENT_ID` / `LINKEDIN_ADS_CLIENT_SECRET`, or a static `LINKEDIN_ADS_ACCESS_TOKEN` (or integration `accessToken`) without them.
- **LinkedIn token expiry:** with `LINKEDIN_ADS_REFRESH_TOKEN` set, each sync trades it for a fresh 60-day access token, so only the refresh token (about a year) needs replacing by hand. Without it, the static access token lasts 60 days. Each `platform_metrics_sync` run logs `linkedin_ads_token_expiring days_left=N` once the token that expires first (the refresh token, or the static access token read through introspection with the client id/secret) is within `LINKEDIN_ADS_TOKEN_WARN_DAYS` (default 30); the run result also carries `linkedin_token_days_left`. A CloudWatch metric filter on that log line drives the `linkedin-ads-token-expiring` alarm, and `platform_metrics_sync_errors` drives the `platform-metrics-sync-errors` alarm (`platform_metrics_sync.tf`; console only, no SNS yet). To renew, re-authorize with an account that can read the ad account and update the `LINKEDIN_ADS_REFRESH_TOKEN` GitHub environment secret. An expired or revoked token makes the sync fail, and report inputs show LinkedIn as `error`.
- **Report inputs:** a requested social platform with no snapshot in the window is `error` when its latest sync failed, otherwise `missing`.

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
