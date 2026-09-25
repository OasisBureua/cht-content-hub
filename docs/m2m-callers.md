# Hub M2M: one client per env, token on every CRUD call

Hub gets **its own Cognito M2M app client per environment** (dev / test / prod).
That is Hub’s service identity.

Every Hub HTTP surface that is essentially CRUD must take
`Authorization: Bearer <access_token>`. The token’s scopes must match the
**operation** (read / create / update / delete) on that resource. No more
shared `X-API-Key` / `INTERNAL_CACHE_SECRET` for those paths.

User logins stay Cognito **user** JWTs (`chm-*` groups). WordPress HMAC and
S3→Lambda notify are not HTTP CRUD and stay as they are.

---

## 1. Hub’s client (per env)

| Env | Suggested client / secret | Used when Hub calls out |
|---|---|---|
| Dev | `cht-hub-m2m-dev` → SM `cht-dev-cognito-m2m-hub` | `devapp` / `devhub` |
| Test | `cht-hub-m2m-test` → SM `cht-test-cognito-m2m-hub` | `testapp` / `testhub` |
| Prod | `cht-hub-m2m-prod` → SM `cht-prod-cognito-m2m-hub` | `app` / `contenthub` |

One client, several **scopes** (do not create a new client per Hub job):

| Scope | Hub uses it for |
|---|---|
| `platform/export.read` | `GET …/input-packet` (`platform_export_ingest`) |
| `platform/cache.clear` | `POST /api/internal/cache/clear` (API + sync jobs) |

`vtt_object_ingest` does not use this client (S3 GetObject + IAM only).

JSON in SM: `{ "client_id", "client_secret", "token_url", "scope" }`.
Hub Lambdas/API load the **env** secret, request a token with only the
scopes that call needs, send `Authorization: Bearer`.

---

## 2. Inbound: token required on Hub CRUD

Hub is the resource server. Callers (platform, reports, later companion /
DaaS) use **their** M2M client to get a token, then call Hub. They never
share Hub’s client secret.

| Operation | Scope shape | Typical Hub routes |
|---|---|---|
| Read | `hub/{resource}.read` | `GET /api/public/*`, `GET /api/campaigns/{id}/report-packet`, `GET /api/admin/…` |
| Create | `hub/{resource}.create` | `POST /api/admin/…`, `POST /api/public/hcp/upsert` |
| Update | `hub/{resource}.update` | `PATCH /api/admin/clips`, playlists, KOLs, tags |
| Delete | `hub/{resource}.delete` | admin deletes / unlinks |

Start with a small resource set and grow; do not mint a scope per URL.

| Resource | Covers |
|---|---|
| `catalog` | clips, playlists, tags, doctors, transcripts, wordpress reads |
| `admin` | studio writes (clips/playlists/KOLs/tags/campaigns) |
| `reports` | report-packet |
| `webhooks` | only if ops-console moves off `WEBHOOK_API_KEY` |

Examples:

- Platform BFF `GET /api/public/clips` → Bearer with `hub/catalog.read`
- Platform admin `PATCH /api/admin/clips/{id}` → `hub/admin.update`
- cht-reports `GET /api/campaigns/42/report-packet` → `hub/reports.read`

Reject missing/expired token or a token that only has `.read` on a `PATCH`.
`X-API-Key` is not accepted on these paths.

**Not token CRUD**

| Path | Auth | Why |
|---|---|---|
| `/health` | none | probe |
| `/api/wordpress/webhook` | HMAC | WordPress, not Cognito |
| `/webhook/*` | `WEBHOOK_API_KEY` until ops M2M | then `hub/webhooks.create` |
| Staff SPA | user JWT + `chm-*` | not `client_credentials` |
| S3 → `vtt_object_ingest` | `lambda:AddPermission` | not HTTP |

---

## 3. Who calls platform (Hub outbound)

| Caller | Platform endpoint | Today | Target |
|---|---|---|---|
| `platform_export_ingest` + admin export-ingest | `GET /api/export/reports/campaigns/{id}/input-packet` | M2M `platform/export.read` (`cht-*-cognito-m2m-export`) | Same scopes on **Hub’s per-env client** (merge/replace the export-only client) |
| Cache clear (`admin/cache.py`, `cht_cache.py`) | `POST /api/internal/cache/clear` | `INTERNAL_CACHE_SECRET` `?cacheKey=` | Hub client + `platform/cache.clear` |
| `vtt_object_ingest` | none | IAM GetObject | no token |
| Report-packet | none | — | reports calls Hub with `hub/reports.read` |

---

## 4. Who calls Hub (they send a token)

| Caller | Hub CRUD | Today | Token they must send |
|---|---|---|---|
| cht-platform-tool catalog | read catalog | Bearer | `hub/catalog.read` |
| cht-platform-tool admin | CUD admin | Bearer | `hub/admin.create` / `.update` / `.delete` |
| cht-reports | read report-packet | Bearer | `hub/reports.read` |
| cht-companion / DaaS | when they get routes | — | own client + the CRUD scope for that route |
| ops-console | create webhook events | API key | later `hub/webhooks.create` |

Each of those products has **its own** M2M client (per env). Hub’s client is
only for Hub calling platform. A reports leak must not be able to `PATCH`
clips.

---

## 5. Clients to stand up

| Client | Owner | Env copies | Requests |
|---|---|---|---|
| `cht-hub-m2m-{env}` | Content Hub | dev, test, prod | `platform/export.read`, `platform/cache.clear` |
| `cht-platform-m2m-{env}` | Platform | same | `hub/catalog.read`, `hub/admin.*` |
| `cht-reports-m2m-{env}` | Reports | same | `hub/reports.read` |
| Companion / DaaS | that product | when needed | only the CRUD scopes they use |

Fold `cht-dev-cognito-m2m-export` into `cht-hub-m2m-dev` when convenient so
Hub has **one** identity per env, not one client per job.

---

## 6. Env vars (Hub)

| Job / service | Token? | Set |
|---|---|---|
| API + `platform_export_ingest` | Yes (outbound) | Hub M2M SM ARN per env; `PLATFORM_EXPORT_BASE_URL` |
| Cache clear | Yes (outbound) | same Hub M2M client; drop `INTERNAL_CACHE_SECRET` after cutover |
| `vtt_object_ingest` | No | `PLATFORM_EXPORT_TRANSCRIPT_BUCKET` only (`cht-dev-session-assets` / `cht-platform-session-assets`) |
| Inbound CRUD | Caller sends token | Hub validates JWKS + scope vs method |

---

## 7. Dev slice (Hub, live now)

Inbound CRUD is guarded:

| Route family | Bearer scope for GET | Other verbs |
|---|---|---|
| `/api/public/*` | `hub/catalog.read` | `hub/catalog.create` / `.update` / `.delete` |
| `/api/admin/*` | `hub/admin.read` | `hub/admin.create` / `.update` / `.delete` |
| `GET /api/campaigns/{id}/report-packet` | `hub/reports.read` | — |

`X-API-Key` is rejected. Callers must send a Bearer token with the matching
CRUD scope.

**Platform-tool call (dev)**

1. Create a resource server `hub` on the CHT Cognito pool with scopes
   `catalog.read`, `admin.read`, `admin.create`, `admin.update`, `admin.delete`,
   `reports.read` (Cognito exposes them as `hub/catalog.read`, …).
2. App client `cht-platform-m2m-dev` allowed those scopes (`client_credentials`).
3. Set Hub `hub_m2m_issuer` (tfvar) to
   `https://cognito-idp.us-east-1.amazonaws.com/<userPoolId>`.
4. Token then request:

```http
POST {token_url}
Content-Type: application/x-www-form-urlencoded
Authorization: Basic base64(client_id:client_secret)

grant_type=client_credentials
scope=hub/catalog.read hub/admin.read hub/admin.update
```

```http
GET https://devhub.communityhealth.media/api/public/tags
Authorization: Bearer <access_token>
```

Wrong scope → 403. Missing or invalid token → 401.

## 8. Cutover

1. Create Hub resource-server scopes (CRUD) and Hub’s per-env client.
2. Hub: Bearer required on `/api/public/*`, `/api/admin/*`, report-packet; map HTTP verb → `.read` / `.create` / `.update` / `.delete`.
3. Platform + reports: their per-env clients request those scopes; send the token.
4. Hub outbound: cache-clear and export use Hub’s client.
5. Drop unused `PUBLIC_API_KEY` / `INTERNAL_CACHE_SECRET` from Secrets Manager when callers are all on M2M.
