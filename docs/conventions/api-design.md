# API design

## Endpoint consolidation

Prefer fewer, parameter-driven endpoints over proliferating one endpoint per variation.

### Bad

```
GET /clips/by-doctor
GET /clips/by-shoot
GET /clips/by-tag
GET /clips/by-date-range
GET /clips/featured
GET /clips/recent
```

Six endpoints, six API docs entries, six places to add a new filter, six places to apply RBAC.

### Good

```
GET /clips?doctor=<slug>&shoot=<id>&tag=<tag>&from=<date>&to=<date>&featured=true&sort=recent
```

One endpoint, one API doc entry. New filters are new query parameters. RBAC is applied once.

## Role-based access within shared endpoints

Cognito group claims gate **what is returned**, not which endpoint is called. A single endpoint may return different fields, different row sets, or different aggregations based on the caller's group — but it remains one endpoint.

Groups:

- `chm-admin` — full platform + studio access
- `chm-editor` — studio only, scoped by `client_ids` claim
- `chm-viewer` — read-only studio

End users (HCPs, KOLs) authenticate without group membership; their access is gated by `client_ids` scoping.

Example: `GET /api/admin/studio/clips/{id}` returns:
- For an `chm-admin`: full clip metadata including internal flags, tag audit history, render job state
- For an `chm-editor`: clip metadata except internal flags, filtered by client_ids scope
- For an `chm-viewer`: read-only studio view

The route handler inspects the group claim and shapes the response. No separate `/admin/clips/{id}` and `/viewer/clips/{id}`.

## When to break the rule

Some operations are genuinely distinct and should not share an endpoint:

- Different HTTP verbs (`GET /clips` vs `POST /clips`) — always separate
- Operations that mutate fundamentally different resources
- Operations with materially different rate limits, auth requirements, or SLA expectations

When in doubt, prefer consolidation. It's cheaper to split a consolidated endpoint later than to merge proliferated ones.
