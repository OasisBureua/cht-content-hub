# KOL + HCP Intel migration spec

**Status:** Approved target state — June 2026  
**Owner:** Uche Aduakaa  
**Scope:** Everything KOL- and HCP-Intel-related moves from `chm-mediahub` into `cht-content-hub` at the **backend + data layer**. MediaHub retains **zero** ownership of KOL data, static assets, APIs, or HCP Intel after cutover. Frontend is rebuilt separately against Content Hub APIs.

> **Supersedes** interim language in [contenthub-admin-architecture.md](./contenthub-admin-architecture.md) decision #5 ("backed by MediaHub RDS until a future HCP intel migration"). HCP Intel migrates **with** KOL in the same cutover — not as a follow-on.

**Related:** [contenthub-migration-plan.md](./contenthub-migration-plan.md) · [cht-public-api-contract.md](./cht-public-api-contract.md) · [contenthub-admin-architecture.md](./contenthub-admin-architecture.md)

**Frontend:** Consumer and admin UIs are being **redone from scratch**. This migration delivers **backend + data + API contracts only**. No React/Next.js pages, components, or E2E specs are ported from MediaHub or cht-platform-tool.

---

## 1. Final-state principle

| System | After cutover |
|--------|---------------|
| **cht-content-hub** | Single system of record: KOL + HCP Intel tables, public producer API, admin studio API, static headshots (CDN), ingestion jobs |
| **New frontend** (consumer + admin) | Built against Content Hub APIs. Legacy UIs in MediaHub and cht-platform-tool are **reference only** — not ported. |
| **chm-mediahub** | Client analytics, webhooks, report generator (if retained). **No** KOL routes, tables, static files, or HCP Intel. May read KOL/HCP counts via Content Hub API for dashboards. |

```text
contenthub.communityhealth.media
├── /kol-network/*                    New consumer UI (rebuild)
├── /admin/studio/kols/*              New admin UI (rebuild)
├── /admin/studio/hcp-intel/*         New admin UI (rebuild)
├── /api/public/kols/*                Producer (X-API-Key) — server-to-server + optional BFF
├── /api/public/hcp/upsert            CHT registration sync (X-API-Key)
├── /api/admin/studio/kols/*          KOL CMS + group management (Cognito JWT)
├── /api/admin/studio/hcp-intel/*     HCP Intel admin API (Cognito JWT)
└── CDN /assets/kols/*                Headshots + report photos

devhub.communityhealth.media / contenthub.communityhealth.media        (no KOL, no HCP Intel)
├── /dashboard/*                      Analytics (optional read-only Content Hub calls)
├── /webhook/sync                     Ingest pipeline
└── /api/...                          Reports, client metrics — zero KOL/HCP Intel routes
```

### 1.1 Frontend redo — what changes vs what stays

| In scope (migrate) | Out of scope (do not port) |
|--------------------|----------------------------|
| Public producer API + schemas | MediaHub `/dashboard/hcps/*` pages (12) |
| Admin studio API (~60 routes) | MediaHub KOL group dashboard pages |
| Database tables + data dump | `KOLGroupCard`, `KOLChip`, HCP Intel components |
| Lambda / ingestion jobs | cht-platform-tool `DolNetwork`, `KolProfilePage`, `DolRegionDetail` |
| Headshots → S3/CDN | `dol-network.ts` static mock + `useKolDirectory` merge logic |
| **API contract docs** (handoff to frontend team) | E2E specs (`hcp-intel/*.spec.ts`) |
| CHT `hcp/upsert` server path (registration) | cht-platform-tool `kol-network` proxy module (optional — drop if new frontend calls Content Hub directly) |

**Handoff artifact for frontend:** OpenAPI or typed schema exports from Content Hub plus the route map in §3 and enrichment field list in §6.1. Existing pages are **behavioral reference** (what screens exist, what data they show) — not copy sources.

---

## 2. Is HCP Intel required? (Recommendation: **yes — migrate wholesale**)

HCP Intel is not optional if KOL network is in scope. The two domains are tightly coupled:

| Coupling | Why it blocks a KOL-only migration |
|----------|-------------------------------------|
| **Publications** | `GET /api/public/kols/{slug}/publications` reads `hcp_signals` via `kols.hcp_npi` |
| **KOL ↔ HCP link** | `kol_hcp_matcher.py` resolves `kols.hcp_npi` → `hcps.npi` |
| **Rankings** | Global KOL rankings and CHM engagement tiers are computed entirely from HCP Intel tables (`rankings.py`, webinar attendance, Rx volumes, NCI designations) |
| **CHT registration** | `POST /api/public/hcp/upsert` fires on every CHT signup/profile update — populates `hcps` that KOL matcher and enrichment depend on |
| **Profile enrichment fields** | Fields previously mocked in legacy `dol-network.ts` (NPI, AI brief, Open Payments, social URLs) must be served by the API from HCP Intel tables (`hcp_ai_briefs`, `open_payments_records`, `hcps.enrichment_data`) before the new frontend ships |
| **Admin workflows** | Review queue, NPI disambiguation, OpenAlex backfill, and data-quality tooling are all HCP Intel — needed to keep KOL profiles accurate |

**Verdict:** Migrate HCP Intel **with** KOL in one cutover. Splitting them leaves publications broken, rankings orphaned, and admin staff bouncing between two systems.

### What HCP Intel provides (business value)

| Capability | Primary consumers |
|------------|-------------------|
| HCP roster + NPI resolution | Admin directory, CHT registration sync |
| Signal timeline (pubs, trials, news, Rx shifts) | HCP profile pages, KOL profile enrichment |
| OpenAlex publications | Public `/kol-network` publications tab |
| Webinar attendance + CHM engagement | CHM KOL rankings, prescriber impact |
| CMS Part D / Rx volumes | Prescriber impact, global KOL rankings |
| Open Payments + NIH grants | HCP profile detail, AI briefs |
| Review queue + data quality | Ops team daily workflow |
| AI briefs (Claude Haiku) | Profile enrichment, future public KOL detail |

---

## 3. Source inventory (chm-mediahub → cht-content-hub)

### 3.1 Public producer API

Port from `chm-mediahub/backend/src/`:

| Endpoint | Handler | Module |
|----------|---------|--------|
| `GET /api/public/kols` | `get_public_kols` | `public/router.py` |
| `GET /api/public/kols/{slug}` | `get_public_kol_detail` | `public/router.py` |
| `GET /api/public/kols/{slug}/publications` | `get_public_kol_publications` | `public/router.py` |
| `POST /api/public/hcp/upsert` | `hcp_upsert` | `public/router.py` + `services/hcp_upsert.py` |

Supporting modules:

| File | Purpose |
|------|---------|
| `models/kol.py` | `KOL`, `KOLGroup`, `KOLGroupMember` |
| `schemas/public.py` | `PublicKOL*`, `PublicKOLPublication*`, `HCPUpsert*` |
| `utils/public.py` | `kol_slug`, `kol_to_public`, `build_kol_slug_map` |
| `services/kol_regions.py` | Region taxonomy + institution inference |
| `hcp_intel/models.py` | All HCP Intel SQLAlchemy models |
| `hcp_intel/kol_hcp_matcher.py` | KOL → NPI matching |
| `hcp_intel/rankings.py` | Global + CHM KOL rankings |
| `hcp_intel/openalex_backfill.py` | Publication ingestion |
| `hcp_intel/orchestrator.py` | Feed polling orchestration |
| `hcp_intel/*` (full package) | Ingestion, disambiguation, AI brief, webinar, Rx, etc. |

Legacy shim to retire after cutover: `legacy/routers/public_api.py`.

### 3.2 Admin studio API

Port from `chm-mediahub/backend/legacy/routers/hcp_intel.py` (~60 routes) under `/api/admin/studio/hcp-intel/*`:

| Route group | Examples |
|-------------|----------|
| Roster | `GET/POST /hcps`, `GET/PATCH /hcps/{npi}`, promote, timeline |
| Discovery + review | `/discovery`, `/review/queue`, `/review/{id}` |
| Rankings | `/rankings/global`, `/rankings/chm`, `/kols` roster |
| Analytics | `/overview`, `/geo/states`, `/prescriber-impact`, `/cohort-flow` |
| Webinars | `/webinars`, attendance, drugs, JotForm webhook |
| Medications | `/medications`, `/manufacturers`, `/drugs/search` |
| Per-HCP detail | NIH grants, Open Payments, AI brief, Rx, engagement, news, shifts |
| Admin ops | poll, OpenAlex backfill, signal purge, data-quality, ensure-plumbing |

Also port KOL group admin from `legacy/routers/clients.py` (KOL-specific routes only) under `/api/admin/studio/kols/*`:

| Route | Purpose |
|-------|---------|
| `GET /kols` | Global KOL list |
| Project KOL group CRUD | Groups, members, stats (currently under `/api/clients/...`) |

### 3.3 Admin UI — reference only (new frontend rebuild)

Do **not** port MediaHub or cht-platform-tool frontend code. Use legacy pages as a **feature checklist** for the new admin SPA. Each row maps a screen the new UI should cover to the studio API routes it consumes.

**HCP Intel screens** (legacy: `chm-mediahub/frontend/src/app/dashboard/hcps/`):

| Screen (new route TBD) | Studio API consumed | Legacy reference |
|------------------------|----------------------|------------------|
| Overview | `GET /overview`, `/geo/states` | `/dashboard/hcps` |
| HCP directory | `GET /hcps` | `/dashboard/hcps/directory` |
| HCP profile | `GET /hcps/{npi}`, timeline, grants, payments, ai-brief, rx, engagement | `/dashboard/hcps/[npi]` |
| Global KOL rankings | `GET /rankings/global` | `/dashboard/hcps/kol-rankings` |
| CHM KOL rankings | `GET /rankings/chm` | `/dashboard/hcps/chm-kol-rankings` |
| Prescriber impact | `GET /prescriber-impact` | `/dashboard/hcps/prescriber-impact` |
| Medications | `GET /medications`, `/manufacturers` | `/dashboard/hcps/medications` |
| Webinars | `GET/POST /webinars`, drugs, forms | `/dashboard/hcps/webinars` |
| Surveys | `GET /surveys` | `/dashboard/hcps/surveys` |
| Review queue | `GET /review/queue`, `POST /review/{id}` | `/dashboard/hcps/review` |
| Data quality | `GET /admin/data-quality/*` | `/dashboard/hcps/data-quality` |

**KOL admin screens** (legacy: client dashboard):

| Screen (new route TBD) | Studio API consumed | Legacy reference |
|------------------------|----------------------|------------------|
| KOL roster | `GET /kols` | — |
| Project KOL groups | project + group list endpoints | `/dashboard/clients/.../projects/...` |
| KOL group detail | group detail + members + clips | `/dashboard/clients/.../groups/[groupId]` |

### 3.4 Static assets

| Asset | Source path | Count | Target |
|-------|-------------|-------|--------|
| KOL headshots | `backend/legacy/static/kol-headshots/` | 29 PNG | S3 + CloudFront; rewrite `kols.photo_url` |
| Report KOL photos | `backend/legacy/report_automation/assets/kol_photos/` | ~15 JPG | Same bucket; report generator reads from Content Hub CDN |

Retire MediaHub mount: `legacy/main.py` → `StaticFiles(directory=_static_dir)`.

### 3.5 Legacy frontend — retire, do not migrate

These files in cht-platform-tool and MediaHub are **superseded by the frontend redo**. No action during backend migration except ensuring API fields exist before the new UI launches.

| Legacy file | Disposition |
|-------------|-------------|
| `cht-platform-tool/.../dol-network.ts` | Retire — enrichment must come from API |
| `cht-platform-tool/.../useKolDirectory.ts` | Retire |
| `cht-platform-tool/.../DolNetwork.tsx`, `KolProfilePage.tsx`, `DolRegionDetail.tsx` | Retire |
| `chm-mediahub/frontend/.../dashboard/hcps/*` | Retire after new admin UI ships |
| `chm-mediahub/frontend/.../KOLGroupCard.tsx`, `KOLChip.tsx` | Retire |

---

## 4. Database tables

### KOL (required)

| Table | Purpose |
|-------|---------|
| `kols` | KOL profiles + `hcp_npi` bridge |
| `kol_groups` | Shoot groupings |
| `kol_group_members` | KOL ↔ group links |

Also required for shoot stats on public KOL API: `shoots` (via `kol_group_id`).

### HCP Intel (required — migrate with KOL)

| Table | Purpose |
|-------|---------|
| `hcps` | NPI-keyed identity; CHT upsert target |
| `feed_sources` | Source registry (PubMed, OpenAlex, etc.) |
| `feed_subscriptions` | Per-HCP polling state |
| `feed_items` | Raw ingested items |
| `hcp_signals` | Derived facts (publications, trials, news, …) |
| `signal_drugs` | Drug linkage on signals |
| `webinar_events` | CHM webinar catalog |
| `webinar_attendance` | CHM engagement (CHM rankings) |
| `webinar_drugs` | Drug tags on webinars |
| `webinar_forms` | JotForm bindings |
| `unmatched_attendees` | Attendee resolution queue |
| `rx_volumes` | CMS Part D prescriber data |
| `rx_drug_aliases` | Drug name normalization |
| `drug_classes` | Therapeutic class taxonomy |
| `drug_to_class` | Drug ↔ class mapping |
| `medications` | Medication catalog |
| `manufacturers` | Manufacturer catalog |
| `open_payments_records` | Sunshine Act data |
| `hcp_nih_grants` | NIH grant data |
| `hcp_ai_briefs` | Claude-generated profile briefs |
| `nci_designations` | NCI center prestige (global rankings) |
| `data_sync_state` | Ingestion job health |

### Alembic migrations to port (from chm-mediahub)

KOL-specific:

- `7c596193eb7d_add_multi_tenant_models.py`
- `a5b6c7d8e9f0_add_kol_region_columns.py`
- `c4665648bc07_add_metadata_fields_to_kol_groups_and_.py`
- `b5c6d7e8f9a0_kol_hcp_link.py`
- `d8e9f0a1b2c3_kol_hcp_unify.py`

HCP Intel: all migrations touching `hcps`, `hcp_signals`, and related tables (grep `hcp_intel` / table names in `backend/migrations/versions/`).

---

## 5. Background jobs (Lambda catalog)

From [sync/README.md](../sync/README.md) and `backend/src/jobs/scheduler.py`:

| Job | Schedule | Purpose |
|-----|----------|---------|
| `hcp_intel_poll` | 30m | Feed orchestrator — PubMed, ClinicalTrials, Google News, etc. |
| `hcp_intel_openalex_backfill` | Sun 03:30 UTC | Publication signals for linked HCPs |
| `kol_hcp_matcher` | On-demand or daily | Resolve `kols.hcp_npi` |
| `post_tagging` | 12h | Keyword + KOL name tags on clips |
| `platform_sync` | 12h | YouTube/LinkedIn/X ingest |
| `ai_summaries` | 12h | Clip/shoot AI descriptions |

**Drop:** `kol_cache_warm` — CHT owns Redis (`cht:kol-network:{hash(params)}`).

Additional on-demand admin ops (triggered from studio API, not scheduled): signal purge, ensure-plumbing, resolve-unmatched, re-ingest-webinars, CMS Part D load, Open Payments sync, NIH sync.

---

## 6. Frontend integration (new build)

### 6.1 Public API contract — consumer `/kol-network`

Document these shapes for the new frontend team (extend [cht-public-api-contract.md](./cht-public-api-contract.md) as needed):

**`GET /api/public/kols`** — list + facets

| Field | Type | Notes |
|-------|------|-------|
| `items[].id`, `slug`, `name`, `title`, `specialty`, `institution`, `bio`, `photo_url` | string | Core profile |
| `items[].region`, `region_label` | string | Filter chips |
| `items[].shoot_count`, `first_appeared_at`, `is_new` | int / datetime / bool | Engagement signals |
| `regions[]`, `institutions[]` | facets | Directory filters |
| Query: `region`, `institution`, `q`, `new_only`, `limit`, `offset` | | |

**`GET /api/public/kols/{slug}/publications`** — publication list (empty array OK).

**Enrichment fields to add before new UI ships** (currently mocked in legacy `dol-network.ts`):

| Field | Source table / join |
|-------|---------------------|
| `npi` | `kols.hcp_npi` → `hcps.npi` |
| `education` | `hcps.enrichment_data` or new column |
| `linkedInUrl`, `twitterUrl`, `webUrl` | `hcps.enrichment_data` |
| `aiBrief` | `hcp_ai_briefs` |
| `openPayments` summary | `open_payments_records` aggregate |
| `publicationsApprox` | count from `hcp_signals` |

Either extend `PublicKOL` on the detail endpoint or add `GET /api/public/kols/{slug}/enrichment` — decide before frontend build starts.

### 6.2 Admin studio API — new admin UI

All routes under `/api/admin/studio/hcp-intel/*` and `/api/admin/studio/kols/*` with Cognito session JWT + `chm-admin` / `chm-editor` / `chm-viewer` group checks. Export OpenAPI from FastAPI for frontend code generation.

### 6.3 CHT registration path (server-to-server — still required)

Independent of consumer UI redo. CHT backend must call Content Hub on signup/profile update:

| Caller | Target |
|--------|--------|
| Registration / profile sync | `POST {CONTENTHUB}/api/public/hcp/upsert` |

Set `CONTENTHUB_BASE_URL` in cht-platform-tool (or successor backend).

**Optional retirement:** `cht-platform-tool/backend/src/modules/kol-network/` proxy module — drop if new frontend or BFF calls Content Hub public API directly with appropriate auth. Registration upsert stays on CHT backend regardless.

### 6.4 Consumer screens — reference checklist (new frontend)

| Screen | Public API |
|--------|------------|
| KOL directory (region/state filters) | `GET /kols` |
| KOL profile | `GET /kols/{slug}` + publications + enrichment |
| Region detail | `GET /kols?region=…` |

Legacy reference: `cht-platform-tool/frontend/src/pages/public/DolNetwork.tsx`, `KolProfilePage.tsx`, `DolRegionDetail.tsx`.

---

## 7. Cutover phases

### Phase 1 — Data + producer API (backend only)

- [ ] pg_dump all KOL + HCP Intel tables (see §4) into Content Hub Aurora
- [ ] Upload headshots to S3; rewrite `kols.photo_url`
- [ ] Port `backend/src/` producer code (public KOL + HCP upsert)
- [ ] Port full `hcp_intel/` package
- [ ] Deploy `contenthub-api` to ECS; smoke test public endpoints
- [ ] Wire Lambda jobs (`hcp_intel_poll`, `openalex_backfill`, `post_tagging`)
- [ ] Publish API contract doc / OpenAPI for frontend team (§6)

### Phase 2 — Server integration

- [ ] Point CHT registration sync to Content Hub (`POST /hcp/upsert`)
- [ ] Verify HCP upsert round-trip from CHT signup flow
- [ ] Extend `PublicKOL` (or enrichment endpoint) with fields in §6.1
- [ ] Smoke test: `curl -H "X-API-Key: $KEY" "$BASE/kols?limit=1"`

*No consumer UI verification in this phase — new frontend not built yet.*

### Phase 3 — Admin studio API (backend only)

- [ ] Port `/api/admin/studio/hcp-intel/*` routes with Cognito JWT middleware
- [ ] Port `/api/admin/studio/kols/*` routes
- [ ] Export OpenAPI for admin studio surface
- [ ] Retire MediaHub `/api/hcp-intel/*` routes once studio API is live

*New admin UI is a separate frontend workstream — consumes studio API when ready.*

### Phase 4 — MediaHub decommission (KOL + HCP Intel)

- [ ] Remove KOL/HCP Intel routes from MediaHub `legacy/main.py` and `src/main.py`
- [ ] Drop KOL + HCP Intel tables from MediaHub Postgres (after validation window)
- [ ] Delete static asset directories from MediaHub repo
- [ ] Retire legacy frontend code in MediaHub + cht-platform-tool (when new UI ships)
- [ ] Update docs: no MediaHub references for KOL or HCP Intel

---

## 8. MediaHub exit criteria (KOL + HCP Intel)

MediaHub backend/data is clear when **all** of the following are true:

- [ ] No `kols`, `kol_groups`, `kol_group_members`, or HCP Intel tables in MediaHub DB
- [ ] No `/api/public/kols*` or `/api/public/hcp/upsert` on MediaHub hostnames
- [ ] No `/api/hcp-intel/*` routes on MediaHub
- [ ] No `/static/kol-headshots/` mount or files in MediaHub deploy artifact
- [ ] CHT registration sync points at Content Hub (not MediaHub)
- [ ] Content Hub public + studio APIs pass smoke tests

Legacy frontend retirement (separate from backend exit criteria — complete when new UI ships):

- [ ] MediaHub `/dashboard/hcps/*` and KOL group pages removed or unreachable
- [ ] cht-platform-tool KOL pages and `dol-network.ts` retired
- [ ] New consumer + admin UIs live against Content Hub APIs

---

## 9. Risk notes

| Risk | Mitigation |
|------|------------|
| Large HCP Intel surface (~60 routes, 22 tables, 140+ source files) | Port `src/hcp_intel/` as a unit; keep legacy router as thin re-export during transition |
| Publications empty until OpenAlex backfill runs | Run backfill immediately after data port; matcher job links KOLs to NPIs first |
| Report generator still references local `kol_photos/` | Point report automation at Content Hub CDN URLs before Phase 4 |
| Client dashboard KOL group counts | Add read-only Content Hub API for analytics embed, or drop counts from MediaHub UI |
| New frontend blocked on enrichment fields | Ship §6.1 enrichment on API before frontend build; do not recreate static mocks |
| Frontend team starts before OpenAPI exists | Block frontend kickoff until Phase 1 publishes contract doc |

---

## 10. File manifest (backend port targets)

**Port to cht-content-hub:**

```
chm-mediahub/backend/src/
├── models/kol.py
├── schemas/public.py          (KOL + HCP upsert schemas)
├── utils/public.py            (slug helpers)
├── services/kol_regions.py
├── services/hcp_upsert.py
├── public/router.py           (KOL + HCP upsert handlers)
└── hcp_intel/                 (entire package — 30+ modules, tests)

chm-mediahub/backend/legacy/
├── routers/hcp_intel.py       (admin API → /api/admin/studio/hcp-intel/*)
├── routers/clients.py         (KOL group routes → /api/admin/studio/kols/*)
├── static/kol-headshots/      (29 PNG → S3)
└── report_automation/assets/kol_photos/  (~15 JPG → S3)
```

**Reference only — do not port (frontend redo):**

```
chm-mediahub/frontend/src/app/dashboard/hcps/     (12 pages — screen checklist §3.3)
chm-mediahub/frontend/.../KOLGroupCard.tsx
chm-mediahub/frontend/.../clients/.../groups/

cht-platform-tool/frontend/src/pages/public/Dol*.tsx, KolProfilePage.tsx
cht-platform-tool/frontend/src/data/dol-network.ts
cht-platform-tool/frontend/src/hooks/useKolDirectory.ts
cht-platform-tool/backend/src/modules/kol-network/   (optional retire)
```
