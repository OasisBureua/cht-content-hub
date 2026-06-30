# Content Hub migration plan

**Owner:** Uche Aduakaa  
**Status:** Active — canonical migration runbook  
**Updated:** June 2026  
**Audience:** CHT platform team + Content Hub producer team

Single document for target state, phasing, and step-by-step migration. Supersedes scattered notes across domain research tickets for **execution planning**.

**Related contracts (unchanged detail):**

- [cht-public-api-contract.md](./cht-public-api-contract.md) — CHT catalog API
- [cache-sync-contract.md](./cache-sync-contract.md) — worker/Lambda → CHT cache clear
- [WEBHOOK_API.md](./WEBHOOK_API.md) — ops-console ingest
- [contenthub-admin-architecture.md](./contenthub-admin-architecture.md) — admin routes & group matrix

---

## 1. Executive summary

Migrate from **EC2 monolith MediaHub** to:

1. **Content Hub** — consumer + admin SPA at `contenthub.communityhealth.media` (CHT platform repo).
2. **Content Hub producer** — headless API + **serverless sync** (this repo: `cht-content-hub`).
3. **Two databases** — CHT **Aurora Global** (platform) and producer **Aurora Global** (prod) / **RDS** (dev); never shared, never cross-connected from CHT backend.

**Round 1 dev goal:** Producer API on ECS dev + RDS data port + CHT dev wired via API key + first serverless sync jobs + admin shell on Content Hub.

**End state:** No EC2 monolith, no ECS scheduler worker, no MediaHub-hosted admin UI, no GoTrue end-user auth.

---

## 2. Target state architecture

```text
                         EXTERNAL
    YouTube · LinkedIn · X · Meta · PubMed · Zoom · JotForm · Bill.com · ops-console
                                    │
┌───────────────────────────────────┼───────────────────────────────────────────┐
│ us-east-1 PRIMARY                 │                                           │
│                                   ▼                                           │
│  CloudFront ──► S3  contenthub.communityhealth.media                          │
│                    /              /admin/*                                    │
│                    ▼              ▼                                           │
│              Consumer SPA    Admin SPA (platform + studio sections)             │
│                    │              │                                           │
│                    └──────┬───────┘                                           │
│                           ▼                                                   │
│              ALB ──► cht-platform-backend (NestJS, ECS)                       │
│                           │                                                   │
│              ┌────────────┼────────────┬──────────────┐                       │
│              ▼            ▼            ▼              ▼                       │
│        CHT Aurora   ElastiCache    Cognito        SQS (CME·pay·email)         │
│        Global (w)   cht:catalog:*                                             │
│              │                                                                │
│              │ X-API-Key (server only)                                        │
│              ▼                                                                │
│              ALB ──► contenthub-api (FastAPI, ECS)                              │
│                           │                                                   │
│                           ▼                                                   │
│              Producer Aurora Global (writer)  ←── dev: RDS instance            │
│                           ▲                                                   │
│              EventBridge Scheduler ──► Lambda / SQS ──► sync & tagging jobs   │
│                           │                                                   │
│                           └── POST /internal/cache/catalog/clear ──► CHT       │
│                                                                               │
│  Post-MVP: render/reports workers (ECS GPU / SQS) — not serverless            │
└───────────────────────────────────────────────────────────────────────────────┘

us-east-2 DR: CloudFront/ALB failover · Aurora Global readers · Lambda in active region only
```

### 2.1 Hostnames

| Host | Serves |
|------|--------|
| `contenthub.communityhealth.media` | Consumer SPA + `/admin/*` |
| `contenthub.dev.communityhealth.media` | Dev consumer + admin |
| `devhub.communityhealth.media` / `contenthub.communityhealth.media` | **APIs only** — `/api/public/*`, `/api/admin/studio/*`, `/webhook/*`, `/health` |

Producer API hostnames: **devhub** (dev), **contenthub** (prod).

### 2.2 Services at target

| Service | Dev | Prod | Retired |
|---------|-----|------|---------|
| `cht-platform-backend` | ECS | ECS autoscale | — |
| `contenthub-api` | ECS | ECS autoscale | — |
| **Sync Lambdas** + EventBridge | Yes | Yes | ECS `contenthub-worker` |
| SQS + DLQ (long sync) | Yes | Yes | APScheduler in API |
| `contenthub-render` | — | post-MVP ECS/GPU | inline FFmpeg in API |
| MediaHub Next.js admin | EC2 bridge | — | **Retired** |
| Content Hub Redis | — | — | **Retired** (CHT cache only) |

### 2.3 Databases

| Database | Dev | Prod | Owner data |
|----------|-----|------|------------|
| **CHT platform** | RDS or small Aurora | Aurora Global (ue1 w, ue2 r) | Users, sessions, CME, payments, `client_ids` |
| **Content Hub producer** | **RDS Postgres** Single-AZ | **Aurora Global** (ue1 w, ue2 r) | Clips, posts, shoots, tags, KOLs, HCP intel, tag_audit |

**Rule:** `cht-platform-backend` never connects to producer DB. Integration is HTTP only.

---

## 3. Locked decisions

| Area | Decision |
|------|----------|
| Admin UI | `contenthub.communityhealth.media/admin` — same SPA, same session cookie |
| Admin routes | `/admin/platform/*` (CHT) · `/admin/studio/*` (producer) |
| Cognito groups | `chm-admin`, `chm-editor`, `chm-viewer` — no `contenthub-admin`; `superadmin` → `chm-admin` |
| Client scope | `client_ids` on **CHT Aurora user** row; studio API enforces |
| HCP Intel admin | `/admin/studio/hcp-intel/*` on producer API until future Aurora migration |
| CHT → producer catalog | `X-API-Key` on `/api/public/*` (optional Cognito M2M later) |
| Admin → producer studio | Cognito session JWT on `/api/admin/studio/*` |
| Producer prod DB | Aurora Global |
| Producer dev DB | RDS instance |
| Sync jobs | **Serverless** — EventBridge Scheduler + Lambda (+ SQS for long jobs) |
| Producer domains 5–7 code | Stays in producer repo; not moved into CHT NestJS |
| `shoot_tag_pipeline` | Dormant — do not migrate until product decision |
| `auto_segmenter` | Decommission candidate (zero callers) |

---

## 4. Auth model

```text
End users     → Cognito → session cookie → consumer app (never /admin)
CHM staff     → same login → /admin link → platform + studio APIs
CHT backend   → producer /api/public/*     → X-API-Key only
Admin SPA     → /api/admin/studio/*        → session JWT + chm-* group + client_ids
Sync Lambda   → producer Aurora            → IAM VPC role
Lambda        → CHT cache clear            → INTERNAL_CACHE_SECRET
ops-console   → /webhook/sync              → WEBHOOK_API_KEY
```

See [contenthub-admin-architecture.md](./contenthub-admin-architecture.md) for group × nav matrix.

---

## 5. Domain disposition (producer codebase)

### Domain 5 — Content tagging

| Component | Target | Notes |
|-----------|--------|-------|
| `post_tagger` | Producer lib / Lambda layer | Foundation — 8+ importers |
| `playlist_doctor_tagger`, `playlist_title_parser` | **Lambda** cron 04:30 UTC | Required for doctor tags |
| `post_tagging` | **Lambda** 12h | Keyword + KOL tags |
| `shoot_tag_derivation`, `shoot_tag_distribution` | Dormant | Do not schedule |
| `kol_regions` | Producer `src/` | `/api/public/kols` facets |
| `tag_editor` router | `/api/admin/studio/tags` | Admin SPA |
| `campaign_parser` | Studio API | Internal analytics |

### Domain 6 — Video / clip pipeline

| Component | Target | Notes |
|-----------|--------|-------|
| `transcription`, `video_processor` | SQS + Lambda/Fargate | Post-R1 |
| `render_engine`, `ass_generator` | `contenthub-render` ECS GPU + S3 | Post-MVP |
| `transcript_parser` | Producer API lib | `/api/public/transcripts` |
| `routers/render`, `conversations` | `/api/admin/studio/*` | Admin SPA |
| `auto_segmenter` | Retire | — |

### Domain 7 — Cross-cutting

| Component | Target | Notes |
|-----------|--------|-------|
| `public_api` | `contenthub-api` `/api/public/*` | Shrinks as CHT owns endpoints |
| `scheduler` | **EventBridge + Lambda** | Retire ECS worker |
| `redis_store` | Retired | JobStore + CHT Redis |
| `rxnorm_service` | Stays with kb_ai_corrector | — |
| Platform routers (analytics, clients, webhook, …) | Studio API or serverless | See admin route map |
| `users`, `access_requests` | Retire on producer | Cognito + CHT platform |

---

## 6. Serverless sync catalog

Replace `backend/legacy/services/scheduler.py` (21 jobs) with EventBridge Scheduler.

| Job | Schedule | Executor | On success |
|-----|----------|----------|------------|
| Platform sync (YT, LI, X, FB, IG) | 12h | SQS → Lambda/Fargate | cache clear |
| Platform stats | 12h | SQS → Lambda | cache clear |
| `post_tagging` | 12h | Lambda | cache clear |
| `playlist_doctor_tagger` | cron 04:30 UTC | Lambda | cache clear |
| `ai_summaries` | 12h | SQS → Lambda | cache clear |
| `metric_snapshots` | 12h | Lambda | — |
| `linkedin_post_stats_refresh` | 12h | Lambda | — |
| `linkedin_ads_sync` | daily | Lambda | — |
| `linkedin_thumbnail_refresh` | cron 05:00 UTC | Lambda | — |
| `hcp_intel_poll` | 30m | SQS → Lambda | — |
| `hcp_intel_openalex_backfill` | Sun 03:30 UTC | Lambda | — |
| Other `hcp_intel_*` | daily/weekly | Lambda | — |
| **cache_clear** | invoked | Lambda | POST CHT internal endpoint |
| `kol_cache_warm` | — | **Drop** | CHT owns cache |
| `shoot_tag_pipeline` | — | **Do not migrate** | — |

**Rules:** Idempotent handlers · `reserved_concurrency=1` on tagging · DLQ per queue · VPC access to producer DB · secrets from Secrets Manager.

---

## 7. Data migration

### 7.1 Tables — Round 1 dev (minimum)

Port to **producer dev RDS:**

`clips`, `posts`, `shoots`, `kols`, `kol_groups`, `kol_group_members`, `playlist_tags`, `hcps`, `hcp_signals`, `tag_audit`, `tag_proposal`, vocabulary/tag support tables.

**Exclude or sanitize:** `users`, `client_users`, auth tokens, unnecessary PII.

### 7.2 Procedure

```bash
# 1. Stand up producer dev RDS + alembic upgrade head
# 2. Export catalog subset from EC2
pg_dump -Fc -h <ec2> -U mediahub mediahub \
  --table=clips --table=posts --table=shoots \
  --table=kols --table=kol_groups --table=kol_group_members \
  --table=playlist_tags --table=hcps --table=hcp_signals \
  --table=tag_audit --table=tag_proposal \
  -f producer_r1.dump

# 3. Restore
pg_restore -h <dev-rds> -U mediahub -d contenthub_producer \
  --no-owner --no-acl producer_r1.dump

# 4. Validate counts (clips with tags, doctor:* tags, KOLs, transcripts)
# 5. Run sync/tag Lambdas once manually
# 6. CHT dev smoke via API key
```

### 7.3 Prod cutover

1. `pg_dump` EC2 → restore to **producer Aurora Global** primary.  
2. Parallel run EC2 + new stack until 48h stable.  
3. Point CHT prod `CONTENTHUB_BASE_URL` at new API.  
4. Retire EC2.

Detail: [step-4-backend.md](./step-4-backend.md).

---

## 8. Migration phases

### Phase 0 — Prerequisites (parallel CHT Phase 2)

| Step | Owner | Action | Exit |
|------|-------|--------|------|
| 0.1 | CHT | Cognito prod/dev pools stable | End users on Cognito |
| 0.2 | CHT | Groups `chm-admin`, `chm-editor`, `chm-viewer` in Terraform | Groups assignable |
| 0.3 | Both | `PUBLIC_API_KEY` / `CONTENTHUB_API_KEY` in Secrets Manager | Keys rotatable |
| 0.4 | Producer | Block end-user login on legacy MediaHub UI | No learner signup |
| 0.5 | CHT | `/internal/cache/catalog/clear` + Redis `cht:catalog:*` | Contract tests pass |

### Phase 1 — Dev infrastructure (Round 1)

| Step | Owner | Action | Exit |
|------|-------|--------|------|
| 1.1 | Producer | Terraform: producer **dev RDS**, `contenthub-api` ECS, ALB | `/health` 200 |
| 1.2 | Producer | Deploy `contenthub-api` — `/api/public/*` from `backend/src/` | Contract smoke |
| 1.3 | Producer | `pg_dump` → dev RDS restore | Row counts match |
| 1.4 | CHT | Dev `CONTENTHUB_BASE_URL` → dev API | Catalog loads in dev app |
| 1.5 | Producer | First Lambdas: `post_tagging`, `playlist_doctor_tagger`, `cache_clear` | Tags refresh; cache clears |
| 1.6 | CHT | Admin link → `/admin` shell (empty studio OK) | Group-gated nav |

### Phase 2 — Admin & studio API

| Step | Owner | Action | Exit |
|------|-------|--------|------|
| 2.1 | Producer | `/api/admin/studio/*` router + Cognito JWT middleware | 401 without group |
| 2.2 | CHT | Aurora `client_ids` sync on login | Editor scoped to clients |
| 2.3 | CHT | Port `/admin/studio/content` + `/admin/studio/analytics` | Tag editor works |
| 2.4 | Producer | Remaining sync jobs → EventBridge/Lambda | No ECS worker in dev |

### Phase 3 — Studio pipeline & prod infra

| Step | Owner | Action | Exit |
|------|-------|--------|------|
| 3.1 | CHT | Port clipper, conversations, render admin pages | Upload + render smoke |
| 3.2 | Producer | **Producer Aurora Global** prod + Multi-AZ | Terraform promoted |
| 3.3 | Producer | Prod data migration + parallel EC2 | 48h stable |
| 3.4 | CHT | Port `/admin/studio/hcp-intel/*` | Intel queue works |
| 3.5 | Both | DR: ue2 reader, Route53 failover drill | Runbook signed |

### Phase 4 — Decommission

| Step | Owner | Action | Exit |
|------|-------|--------|------|
| 4.1 | Producer | Retire EC2 monolith | No prod traffic to EC2 |
| 4.2 | Producer | Retire MediaHub Next.js admin | Staff use `/admin` only |
| 4.3 | Producer | Retire GoTrue, producer `users` router | Auth checklist signed |
| 4.4 | Both | Retire ECS worker if any remains | All cron on EventBridge |
| 4.5 | Post-MVP | `contenthub-render` GPU + S3 | Clips render off EC2 |

---

## 9. CHT integration checklist

**CHT platform repo**

- [ ] `CONTENTHUB_BASE_URL` per environment  
- [ ] `CONTENTHUB_API_KEY` in Secrets Manager  
- [ ] `INTERNAL_CACHE_SECRET` + cache wrapper  
- [ ] Catalog + KOL services use cache  
- [ ] Admin SPA at `/admin` with Cognito guards  
- [ ] `client_ids` on user model  
- [ ] Remove MediaHub auth URLs from consumer app  

**Producer repo (`cht-content-hub`)**

- [ ] `contenthub-api` ECS service  
- [ ] Producer dev RDS / prod Aurora Global Terraform  
- [ ] `/api/public/*` parity with [cht-public-api-contract.md](./cht-public-api-contract.md)  
- [ ] `/api/admin/studio/*` + CORS for Content Hub origin  
- [ ] EventBridge + Lambda sync pack  
- [ ] Data migration scripts  
- [ ] Retire worker Dockerfile from deploy when Lambdas live  

---

## 10. Round 1 dev exit criteria

- [ ] CHT dev loads catalog from producer dev API (API key)  
- [ ] HCP upsert round-trip works  
- [ ] Sync Lambda runs → CHT cache clear → fresh clips visible  
- [ ] Producer dev RDS populated from EC2 dump  
- [ ] `/admin` reachable for `chm-admin` with studio shell (pages may be stubbed)  
- [ ] No CHT backend connection to producer Postgres  
- [ ] End users cannot auth on legacy MediaHub UI  

---

## 11. Rollback

| Phase | Rollback |
|-------|----------|
| Dev API | Revert CHT `CONTENTHUB_BASE_URL` to EC2 prod URL |
| Prod cutover | Keep EC2 running 48h; revert DNS/env |
| Lambdas | Disable EventBridge rules; re-enable EC2 scheduler temporarily |
| Aurora | Restore snapshot; do not drop EC2 DB until signed off |

---

## 12. Open questions

| # | Question | Default until decided |
|---|----------|----------------------|
| 1 | Rename API hostname to `contenthub.*`? | **Done** — devhub (dev), contenthub (prod) |
| 2 | Cognito M2M instead of API key? | API key for R1 |
| 3 | Lambda vs Fargate for 12h platform sync? | SQS + Lambda; Fargate if timeout hit |
| 4 | KOL data eventual ownership in CHT Aurora? | Producer serves `/api/public/kols` |
| 5 | Admin BFF vs direct studio API calls? | Hybrid — direct for upload/render SSE |

---

## 13. Ticket backlog (starter)

| ID | Title | Phase |
|----|-------|-------|
| CH-01 | Terraform producer dev RDS + API ECS | 1 |
| CH-02 | pg_dump restore script + validation | 1 |
| CH-03 | Lambda: post_tagging, playlist_doctor_tagger, cache_clear | 1 |
| CH-04 | CHT dev env + catalog smoke tests | 1 |
| CH-05 | Cognito chm-* groups + admin link | 0–1 |
| CH-06 | `/admin` layout + guards (CHT repo) | 1 |
| CH-07 | `/api/admin/studio` JWT middleware | 2 |
| CH-08 | Port tag editor + analytics UI | 2 |
| CH-09 | EventBridge full job catalog | 2 |
| CH-10 | Producer Aurora Global prod | 3 |
| CH-11 | Prod cutover + EC2 retire | 3–4 |
| CH-12 | Port hcp-intel admin UI | 3 |
| CH-13 | Render GPU worker (post-MVP) | 4.5 |

---

## 14. Document map

| Doc | Use when |
|-----|----------|
| **This doc** | Migration planning & phase gates |
| [contenthub-admin-architecture.md](./contenthub-admin-architecture.md) | Admin routes, groups, API prefixes |
| [engineering/architecture.md](./engineering/architecture.md) | Producer microservice context |
| [cht-public-api-contract.md](./cht-public-api-contract.md) | Endpoint parity testing |
| [contenthub-migration-plan.md](./contenthub-migration-plan.md) | Cognito cutover day |
| [contenthub-migration-plan.md](./contenthub-migration-plan.md) | Prod pg_dump detail |
| [cache-sync-contract.md](./cache-sync-contract.md) | Lambda → CHT cache |

CHT platform repo: `cht-platform-architecture.pdf`, `cht-platform-auth.pdf`, Cognito Terraform.

**PDF:** run `python3 docs/generate_contenthub_migration_plan.py` to regenerate [Content_Hub_Migration_Plan.pdf](./Content_Hub_Migration_Plan.pdf).
