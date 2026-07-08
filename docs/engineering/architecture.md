# Architecture

Content Hub producer service — headless API + sync jobs powering the clinical content catalog consumed by [cht-platform-tool](https://github.com/OasisBureua/cht-platform-tool).

## Target state

```text
CloudFront → S3  contenthub.communityhealth.media  (/ consumer, /admin CHM staff)
       │
       ▼
ALB → cht-platform-backend (NestJS ECS) → CHT Aurora Global
       │         ElastiCache cht:catalog:*   Cognito   SQS
       │
       │  X-API-Key (server only)
       ▼
ALB → contenthub-api (FastAPI ECS) → Producer Aurora Global (prod) / RDS (dev)
       ▲
       │
EventBridge Scheduler → Lambda / SQS → sync, tagging, HCP intel
       │
       └── POST /internal/cache/catalog/clear → CHT backend
```

**Rule:** `cht-platform-backend` never connects to the producer database. HTTP only.

## This repo owns

| Surface | Prefix | Auth |
|---------|--------|------|
| Public catalog API | `/api/public/*` | `X-API-Key` (CHT backend only) |
| Studio admin API | `/api/admin/studio/*` | Cognito session JWT + `chm-*` groups |
| Webhooks | `/webhook/*` | `WEBHOOK_API_KEY` |
| Health | `/health` | None |

The consumer and admin SPA live in **cht-platform-tool** at `contenthub.communityhealth.media`.

## Databases

| Database | Dev | Prod | Owns |
|----------|-----|------|------|
| CHT platform | RDS | Aurora Global | Users, CME, enrollments |
| Content Hub producer | RDS (5433 local) | Aurora Global | Clips, tags, KOLs, HCP intel |

## Sync job target state

ECS worker APScheduler is a **bridge**. Target catalog (EventBridge + Lambda + SQS):

| Job | Schedule | Cache clear |
|-----|----------|-------------|
| Platform sync (YT/LI/X/FB/IG) | 12h | Yes |
| post_tagging | 12h | Yes |
| playlist_doctor_tagger | 04:30 UTC | Yes |
| hcp_intel_poll | 30m | No |
| cache_clear | on-demand | — |

See [sync/README.md](../sync/README.md) and [contenthub-migration-plan.md](../contenthub-migration-plan.md) §7.

## Phase map

| Phase | Goal |
|-------|------|
| 0 | Cognito groups, API keys in Secrets Manager |
| 1 (Round 1 dev) | Producer API on ECS dev + RDS port + first Lambdas |
| 2 | `/api/admin/studio/*` + tag editor UI in CHT SPA |
| 3 | Prod Aurora Global + EC2 cutover |
| 4 | Retire EC2 monolith, ECS worker, MediaHub admin UI |
