# M2M: one resource server per service

Whoever **owns the HTTP API** owns a Cognito **resource server**. Callers never
share that server. Each caller uses **its own** M2M app client and requests
that server’s scopes.

Same user pool can host every resource server (the CHT pool already has
`platform`). Do **not** hang Hub scopes off the `platform` identifier.

| Service | Resource server | Identifier | Token scopes look like | Who requests them |
|---|---|---|---|---|
| cht-platform-tool | CHT Platform API | `platform` | `platform/export.read` | Hub (outbound) |
| Content Hub | Content Hub API | `hub` | `hub/catalog.read`, `hub/admin.update` | Platform, reports, later companion |
| cht-reports | Reports API (when they expose M2M) | `reports` | `reports/…` | Whoever calls reports |
| Companion / DaaS | their API | their id | `{id}/…` | Their callers |

Hub **calls** platform → Bearer with `platform/…` (Hub’s client).
Platform **calls** Hub → Bearer with `hub/…` (platform’s client).

User logins stay Cognito **user** JWTs (`chm-*` groups). WordPress HMAC and
S3→Lambda notify are not HTTP CRUD.

---

## 1. Hub’s resource server (`hub`)

Terraform (`modules/identity/cognito-m2m`) creates this on the shared pool
when `cognito_user_pool_id` is set. Console name: **Content Hub API**.

Cognito issues `{identifier}/{scope_name}`:

| Scope name | Full token scope | Hub routes |
|---|---|---|
| `catalog.read` / `.create` / `.update` / `.delete` | `hub/catalog.*` | `/api/public/*` |
| `admin.read` / `.create` / `.update` / `.delete` | `hub/admin.*` | `/api/admin/*` |
| `reports.read` | `hub/reports.read` | `GET /api/campaigns/{id}/report-packet` |

HTTP verb → CRUD: GET/HEAD → `.read`, POST → `.create`, PUT/PATCH → `.update`,
DELETE → `.delete`. `hub/{resource}.*` and `hub/{resource}.write` (non-read)
are accepted if a client is granted those names; Cognito itself is created
with the explicit CRUD names only (`*` is not a Cognito scope name).

`X-API-Key` is rejected on these paths.

**Not token CRUD**

| Path | Auth |
|---|---|
| `/health` | none |
| `/api/wordpress/webhook` | HMAC |
| `/webhook/*` | `WEBHOOK_API_KEY` until ops M2M (`hub/webhooks.create`) |
| Staff SPA | user JWT + `chm-*` |
| S3 → `vtt_object_ingest` | IAM / `lambda:AddPermission` |

---

## 2. Hub’s outbound client (per env)

Hub also gets **its own** M2M client. That client does **not** request `hub/…`
(Hub does not call itself). It requests **platform** scopes.

| Env | Client | Secret |
|---|---|---|
| Dev | `cht-hub-m2m-dev` | SM `cht-dev-cognito-m2m-hub` |
| Test | `cht-hub-m2m-test` | SM `cht-test-cognito-m2m-hub` |
| Prod | `cht-hub-m2m-prod` | SM `cht-prod-cognito-m2m-hub` |

| Scope on **platform** RS | Hub uses it for |
|---|---|
| `platform/export.read` | `GET …/input-packet` (`platform_export_ingest`) |
| `platform/cache.clear` | `POST /api/internal/cache/clear` (when that scope exists) |

`vtt_object_ingest` does not use this client (S3 GetObject + IAM).

JSON in SM: `{ "client_id", "client_secret", "token_url", "scope" }`.

Fold `cht-*-cognito-m2m-export` into this client when convenient so Hub has
**one** identity per env.

---

## 3. Other services’ clients (they call Hub)

Each product that calls Hub has **its** client, allowed **only** the `hub/…`
scopes it needs:

| Client | Owner | Allowed Hub scopes |
|---|---|---|
| `cht-platform-m2m-{env}` | Platform | `hub/catalog.read`, `hub/admin.read\|create\|update\|delete` |
| `cht-reports-m2m-{env}` | Reports | `hub/reports.read` |
| Companion / DaaS | that product | only the Hub scopes they use |

Those clients are created by **that** product (or by hand on the shared pool).
Hub terraform does not create platform’s or reports’ clients.

---

## 4. Call map

| Caller | Callee RS | Scope |
|---|---|---|
| Platform catalog | `hub` | `hub/catalog.read` |
| Platform admin | `hub` | `hub/admin.create` / `.update` / `.delete` |
| cht-reports | `hub` | `hub/reports.read` |
| Hub export ingest | `platform` | `platform/export.read` |
| Hub cache-clear | `platform` | `platform/cache.clear` (target) |

---

## 5. Hub env / Terraform

| Env | Pool | `cognito_user_pool_id` | `cognito_auth_domain` |
|---|---|---|---|
| Dev | `cht-dev-users` | `us-east-1_J51gzfO0I` | `chm-dev.auth.us-east-1.amazoncognito.com` |
| Prod | `cht-platform-users` | `us-east-1_whXKKxAdX` | `chm-platform.auth.us-east-1.amazoncognito.com` |

| Input | Purpose |
|---|---|
| `cognito_user_pool_id` | Shared CHT pool. When set, apply creates the `hub` RS + Hub M2M client |
| `cognito_auth_domain` | Host for token URL |
| `HUB_M2M_ISSUER` | `https://cognito-idp.us-east-1.amazonaws.com/<poolId>` (derived if unset) |
| `HUB_M2M_RESOURCE` | Resource-server identifier, default `hub` |
| `HUB_M2M_AUDIENCE` | Optional `aud` / `client_id` check |
| `HUB_M2M_TEST_SECRET` | Tests only (HS256). Never set in AWS |

`vtt_object_ingest`: `PLATFORM_EXPORT_TRANSCRIPT_BUCKET` only.

---

## 6. Platform-tool call (dev)

1. Apply Hub terraform with `cognito_user_pool_id` so **Content Hub API** (`hub`)
   appears next to **CHT Platform API** (`platform`).
2. On platform’s M2M client, allow the `hub/…` scopes above
   (`client_credentials`).
3. Token:

```http
POST https://{cognito_auth_domain}/oauth2/token
Content-Type: application/x-www-form-urlencoded
Authorization: Basic base64(platform_client_id:platform_client_secret)

grant_type=client_credentials
scope=hub/catalog.read hub/admin.read hub/admin.update
```

```http
GET https://devhub.communityhealth.media/api/public/tags
Authorization: Bearer <access_token>
```

Missing token, invalid token, or wrong scope → 401.

## 7. cht-platform-tool (same pool, their client)

Platform does **not** create the `hub` resource server (Hub terraform does).
Platform **does**:

1. App client `cht-platform-m2m-{env}` (`client_credentials`) on the **same**
   pool (`cht-dev-users` / `cht-platform-users`).
2. Allow only Hub scopes they need:
   `hub/catalog.read`, `hub/admin.read`, `hub/admin.create`,
   `hub/admin.update`, `hub/admin.delete`.
3. Store `{ client_id, client_secret, token_url, scope }` in SM
   (e.g. `cht-dev-cognito-m2m-platform`).
4. HTTP interceptor: warm token at startup, in-memory cache, send
   `Authorization: Bearer` on every Hub call (`devhub` / `contenthub`).
   Drop `CONTENTHUB_API_KEY` / `X-API-Key`.
5. Keep `platform` resource server + scopes for **inbound** Hub calls
   (`platform/export.read`). Hub’s client requests those, not `hub/…`.

cht-reports: own client, `hub/reports.read` only.

## 8. Cutover

1. Merge/apply Hub → `hub` RS + `cht-hub-m2m-{env}` appear in Cognito.
2. Platform + reports clients allowed `hub/…`; they send Bearer.
3. Point Hub export at Hub’s client secret (`cht-*-cognito-m2m-hub`).
4. Drop unused `PUBLIC_API_KEY` / `INTERNAL_CACHE_SECRET` after callers are on M2M.
