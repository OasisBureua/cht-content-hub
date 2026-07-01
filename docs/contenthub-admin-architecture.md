# Content Hub admin architecture

**Status:** Approved decisions — June 2026  
**Owner:** Uche Aduakaa  
**Scope:** CHM staff admin UI on Content Hub; Content Hub studio APIs; unified Cognito groups

> **Migration execution:** see [contenthub-migration-plan.md](./contenthub-migration-plan.md) for phased rollout, infrastructure, and data port.

---

## Summary

CHM admins and editors use **one admin application** at `contenthub.communityhealth.media/admin` on the same SPA host as the consumer app. They enter admin only via a link in Content Hub (same session cookie). Producer/editorial tools call **Content Hub studio APIs**; platform ops call **cht-platform-backend**. End users never see `/admin`. Content Hub has **no standalone admin UI** on legacy producer hostnames in target state.

---

## Locked decisions

| # | Decision | Choice |
|---|----------|--------|
| 1 | Admin route namespace | `/admin/studio/*` for Content Hub producer tools; `/admin/platform/*` for CHT platform ops |
| 2 | Hosting | **Same host** — `contenthub.communityhealth.media/admin` (not a separate admin subdomain) |
| 3 | Cognito groups | **`chm-admin`**, **`chm-editor`**, **`chm-viewer`** — fold legacy `superadmin` into `chm-admin`; **no** separate `contenthub-admin` client or group |
| 4 | Multi-tenant client scope | **`client_ids`** (and `has_client_access`) on **Aurora user row**; studio API enforces scope per request |
| 5 | HCP Intel placement | **`/admin/studio/hcp-intel/*`** — backed by Content Hub Aurora/API (see [kol-hcp-intel-migration.md](./kol-hcp-intel-migration.md)) |

---

## System context

```text
contenthub.communityhealth.media
├── /                         Consumer app (HCP, industry, learners)
├── /auth/*                   Cognito login (email + Google — see CHT auth runbook)
└── /admin/*                  CHM staff only (Cognito group gate)
        ├── /admin                      Overview
        ├── /admin/platform/*           cht-platform-backend → Aurora Global
        └── /admin/studio/*             contenthub-api /api/admin/studio/* → Content Hub Aurora

devhub.communityhealth.media / contenthub.communityhealth.media   (post-cutover: no KOL, no HCP Intel)
├── /dashboard/*              Client analytics (optional read-only Content Hub calls)
├── /webhook/*                ops-console (WEBHOOK_API_KEY)
└── /health
```

**No HTML admin UI on MediaHub hostnames.**

---

## Auth model

### Cognito groups

| Group | UI access | Studio write | Platform admin |
|-------|-----------|--------------|----------------|
| `chm-admin` | Full `/admin` | Yes | Yes |
| `chm-editor` | `/admin/studio/*` (scoped) | Yes | No |
| `chm-viewer` | Read-only studio + analytics | No | No |
| `cht-kol`, `cht-hcp`, `cht-pharma-client`, … | Consumer app only | No | No |

Legacy MediaHub roles map as follows:

| Legacy (`public.users.role`) | Target |
|------------------------------|--------|
| `superadmin` | `chm-admin` |
| `admin` | `chm-admin` |
| `editor` | `chm-editor` |
| `viewer` | `chm-viewer` |

### Session flow

Same as CHT platform auth: login → Cognito → `findOrCreateByCognitoSub` → **httpOnly session cookie**. Admin routes reuse that cookie — no second login at MediaHub.

### API auth by surface

| Caller | Target | Auth |
|--------|--------|------|
| End-user browser → CHT backend | Catalog, registration, CME | Session cookie |
| CHT backend → MediaHub | `/api/public/*` | `X-API-Key` (server-only) |
| Admin SPA → CHT backend | `/api/admin/platform/*` | Session cookie |
| Admin SPA → MediaHub | `/api/admin/studio/*` | Session cookie or Bearer (Cognito JWT validated via JWKS + group) |
| MediaHub worker → CHT | `/internal/cache/catalog/clear` | Bearer `INTERNAL_CACHE_SECRET` |

**Do not** forward end-user session tokens to `/api/public/*`. **Do not** use API keys from the admin browser.

### Client scope (decision 4)

Aurora `users` (or equivalent) stores:

- `cognito_sub`
- `groups` (from Cognito token)
- `client_ids: uuid[]` — pharma tenants this user may access
- `has_client_access: boolean` — false for global admins who see all clients

Studio API middleware:

1. Validate JWT + require `chm-admin` | `chm-editor` | `chm-viewer`.
2. If not `chm-admin`, filter queries/mutations to `client_ids`.
3. Return 403 if route client not in scope.

MediaHub `public.users` / `client_users` tables retire after Aurora becomes source of truth for scope.

---

## Admin UI structure

### Entry

- Consumer app shows **Admin** (or **Content Studio**) link when Cognito groups include `chm-admin`, `chm-editor`, or `chm-viewer`.
- Link navigates to `/admin` (same origin).
- Admins never receive links to legacy producer hostnames for UI.

### Sidebar sections

**Platform** (`/admin/platform/*`) — cht-platform-backend

| Route | Capability |
|-------|------------|
| `/admin/platform/users` | Cognito-linked users, group assignment |
| `/admin/platform/access` | Access requests (until fully replaced by groups) |
| _future_ | CME, honorarium, surveys (Zoom, JotForm, Bill.com) |

**Studio** (`/admin/studio/*`) — contenthub-api

| Route | Legacy MediaHub route | Backend (today) |
|-------|----------------------|-----------------|
| `/admin/studio` | `/dashboard` | — |
| `/admin/studio/clipper` | `/dashboard/clipper` | `conversations`, `render` |
| `/admin/studio/conversations/*` | `/dashboard/conversations/*` | `conversations` |
| `/admin/studio/content` | `/dashboard/content` | `tag_editor` |
| `/admin/studio/content/seo` | `/dashboard/content/seo` | SEO |
| `/admin/studio/content/audit` | `/dashboard/content/audit` | `tag_editor` |
| `/admin/studio/clients` | `/dashboard/clients` | `clients` |
| `/admin/studio/analytics` | `/dashboard/analytics` | `analytics` |
| `/admin/studio/campaigns` | analytics campaigns | `campaigns` |
| `/admin/studio/reports` | `/dashboard/reports` | `reports` |
| `/admin/studio/knowledge-base` | `/dashboard/chatbot` | `knowledge_base` |
| `/admin/studio/hcp-intel/*` | `/dashboard/hcps/*` | `hcp_intel` |
| `/admin/studio/integrations` | `/dashboard/settings` | `oauth`, platform connections |

### Group × nav visibility

| Nav item | `chm-admin` | `chm-editor` | `chm-viewer` | Client scope |
|----------|-------------|--------------|--------------|--------------|
| Platform / users | ✓ | — | — | — |
| Studio / clipper | ✓ | ✓ | — | optional |
| Studio / clients | ✓ | ✓ | ✓ | required |
| Studio / analytics | ✓ | ✓ | ✓ | required |
| Studio / content | ✓ | ✓ | ✓ | required |
| Studio / SEO | ✓ | ✓ | — | — |
| Studio / hcp-intel | ✓ | — | — | — |
| Studio / reports | ✓ | ✓ | — | — |
| Studio / integrations | ✓ | — | — | — |

Editors with `requiresClientAccess` nav items need non-empty `client_ids` (same rule as today’s MediaHub sidebar).

---

## MediaHub studio API contract (target)

All producer admin HTTP routes move under:

```text
/api/admin/studio/{domain}/{...}
```

| Domain prefix | Maps from legacy router |
|---------------|-------------------------|
| `/api/admin/studio/conversations` | `routers/conversations` |
| `/api/admin/studio/render` | `routers/render` |
| `/api/admin/studio/tags` | `routers/tag_editor` |
| `/api/admin/studio/analytics` | `routers/analytics` |
| `/api/admin/studio/clients` | `routers/clients` |
| `/api/admin/studio/campaigns` | `routers/campaigns` |
| `/api/admin/studio/templates` | `routers/templates` |
| `/api/admin/studio/hcp-intel` | `routers/hcp_intel` |
| `/api/admin/studio/reports` | `routers/reports` |
| `/api/admin/studio/knowledge-base` | `routers/knowledge_base` |

Legacy paths remain on EC2 monolith until cutover; new admin SPA targets prefixed routes on `contenthub-api`.

**CORS:** `Access-Control-Allow-Origin: https://contenthub.communityhealth.media`, credentials enabled.

---

## Migration phases

| Phase | Deliverable |
|-------|-------------|
| **A0** | Cognito groups `chm-admin` / `chm-editor` / `chm-viewer` in CHT Terraform; deprecate legacy `contenthub-admin` group name if present |
| **A1** | `/admin` shell in Content Hub frontend (layout, guards, empty platform + studio) |
| **A2** | MediaHub: JWT + group middleware on `/api/admin/studio/*`; Aurora `client_ids` sync on login |
| **A3** | Port studio **content** + **analytics** (highest catalog impact) |
| **A4** | Port **clipper / conversations / render** |
| **A5** | Port **hcp-intel** subtree |
| **A6** | Retire MediaHub Next.js admin; block staff login at MediaHub `/login` |

---

## Related documents

| Doc | Scope |
|-----|-------|
| [engineering/architecture.md](./engineering/architecture.md) | Producer microservice + API-only host |
| [cht-public-api-contract.md](./cht-public-api-contract.md) | CHT catalog API key boundary |
| [contenthub-migration-plan.md](./contenthub-migration-plan.md) | End-user auth off; admin via Content Hub |
| [contenthub-migration-plan.md](./contenthub-migration-plan.md) | Parallel CHT / Content Hub tracks |

CHT platform repo: auth PDF, Cognito Terraform, Content Hub frontend implementation.
