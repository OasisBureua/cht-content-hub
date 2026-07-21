# Admin Tag API — Contract (SCRUM-74/75/78)

Small doc for admin tag-write callers. The endpoints ship as part of SCRUM-71
Epic B backend (`PR #82`); they're consumed server-to-server by the
cht-platform-tool CHT proxy (SCRUM-79-82, not yet shipped).

## Auth

`X-API-Key` header, matching every other `/api/admin/*` endpoint. CHT holds
the key and enforces the Studio Cognito JWT + `chm-*` group check before
proxying user requests.

## Base URL

- dev: `https://devhub.communityhealth.media/api/admin`
- prod: `https://contenthub.communityhealth.media/api/admin`

---

## SCRUM-74: playlist tag admin

**Model:** `PlaylistTag` (`youtube_playlist_id`, `tags[]`, `lane`).

### `GET /playlists/{youtube_playlist_id}/tags`

**200 body:**
```json
{
  "youtube_playlist_id": "PL...",
  "tags": ["biomarker:her2-low", "drug:t-dxd"],
  "lane": "biomarker"
}
```

**404** — no `PlaylistTag` row for that YouTube ID.

### `PATCH /playlists/{youtube_playlist_id}/tags`

**Body** (all fields optional; omitted fields untouched):
```json
{
  "tags": ["biomarker:HER2-Low", "drug:Enhertu"],
  "lane": "biomarker"
}
```

**Semantics:**
- `tags` is fully replaced (not merged). Every tag runs through
  `services.tag_taxonomy.normalize_and_validate_tags`: lowercased,
  aliases resolved (Enhertu → t-dxd), typo-corrected, deduped on
  canonical form.
- `lane` must be one of `biomarker | drug | trial | doctor_pair | mixed | archive`;
  `null` clears.

**200** — normalized state after write.

**404** — no `PlaylistTag` row for that YouTube ID (create-if-missing is
NOT supported; caller must ensure the row exists via prior WordPress sync
or seed migration).

**422 — tag validation failure. NestJS-shape envelope with an extra
`rejected` array so the curator UI can show per-tag reasons:**
```json
{
  "statusCode": 422,
  "error": "Unprocessable Entity",
  "message": "One or more tags failed taxonomy validation.",
  "rejected": [
    {"tag": "brand:enhertu", "reason": "unknown namespace 'brand'"},
    {"tag": "not-a-tag", "reason": "not namespaced (expected 'namespace:value')"}
  ]
}
```

**422 — invalid lane** — standard NestJS envelope (no `rejected` array):
```json
{
  "statusCode": 422,
  "error": "Unprocessable Entity",
  "message": "Invalid lane 'nonsense'. Allowed: ['archive','biomarker','doctor_pair','drug','mixed','trial']."
}
```

---

## SCRUM-75: clip tag admin (curator override)

**Model:** `Clip` (`id`, `tags[]`, `tags_curator_override: bool`).

### `GET /clips/{clip_id}/tags`

**200 body:**
```json
{
  "id": "official:youtube:abc123",
  "tags": ["drug:t-dxd", "doctor:Traina"],
  "tags_curator_override": false
}
```

**404** — no `Clip` with that id.

### `PATCH /clips/{clip_id}/tags`

**Body:**
```json
{
  "tags": ["drug:Enhertu", "doctor:Traina"],
  "tags_curator_override": true
}
```

**Semantics:**
- Any `tags` write **auto-sets** `tags_curator_override = true` — the
  playlist doctor-tagger's daily loop will skip this row on subsequent
  runs (mirrors the `kols.curated_fields` sync-respects-manual-lock
  pattern from PR #66).
- Explicit `tags_curator_override: false` in the PATCH re-opens the row
  to the tagger. Rare — typically a rollback.
- `tags` normalized via `services.tag_taxonomy` (same as playlist tags).

**200/404/422** — same shapes as playlist tag PATCH.

---

## SCRUM-78: tagger observability

### `GET /tagger/runs?limit=N`

Recent playlist_doctor_tagger runs. `limit` clamped to 1..100 (default 25).

```json
{
  "items": [
    {
      "id": "uuid",
      "started_at": "2026-07-20T18:00:00Z",
      "finished_at": "2026-07-20T18:04:12Z",
      "mode": "union",
      "dry_run": false,
      "shoots_processed": 27,
      "shoots_doctors_corrected": 3,
      "clips_changed": 12,
      "posts_changed": 8,
      "clips_curator_locked_skipped": 2,
      "posts_curator_locked_skipped": 2,
      "orphaned_404_count": 16,
      "api_error_count": 0,
      "clip_post_skipped_models_missing": false
    }
  ],
  "total": 42
}
```

All timestamps are **UTC ISO 8601**. Frontend should convert to viewer
local time before display.

### `GET /tagger/diffs?limit=N&entity_type=...`

Recent per-entity tag mutations from the tagger. `limit` 1..200 (default 50).
`entity_type` optional filter — `shoot | clip | post`.

```json
{
  "items": [
    {
      "id": "uuid",
      "run_id": "uuid",
      "entity_type": "clip",
      "entity_id": "official:youtube:abc",
      "shoot_id": "shoot-abc",
      "shoot_name": "Traina + Pegram HER2 discussion",
      "provider_post_id": null,
      "title": "Traina + Pegram clip",
      "before_tags": ["drug:t-dxd"],
      "after_tags": ["drug:t-dxd", "doctor:Traina", "doctor:Pegram"],
      "created_at": "2026-07-20T18:03:45Z"
    }
  ],
  "total": 128
}
```

---

## CloudWatch metrics

Emitted from every persisted tagger run (best-effort, silently no-ops
without `AWS_REGION`). Namespace `CHM/ContentHub/Tagger`:

- `TaggerRuns` (Count)
- `ClipsChanged` (Count)
- `PostsChanged` (Count)
- `ApiErrors` (Count)
- `OrphanedPlaylists` (Count)
- `TotalPropagations` (Count, `ClipsChanged + PostsChanged`)

Terraform alarm suggestions (not yet wired):
- `TotalPropagations = 0` over 24h → tagger is broken
- `ApiErrors > 0` over 5min → YouTube Data API issue or auth expiry

---

## Related

- [cache-sync-contract.md](./cache-sync-contract.md) — cache-clear webhook
  fired after any admin write (`scope=contenthub`).
- [contenthub-admin-architecture.md](./contenthub-admin-architecture.md) —
  the broader admin platform vision.
