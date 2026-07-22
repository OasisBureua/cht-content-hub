# Tag Flow Architecture — 2026-07-21

Full end-to-end tag ingestion + surface documentation for the CHM
content pipeline after SCRUM-71 Epic B backend rework.

## Overview

Editorial teams own tag semantics on two external surfaces:

- **WordPress** (communityhealth.media) — WP categories + tags per post,
  edited by Andrew's team
- **YouTube Studio** (chm-official channel) — video snippet.tags,
  edited by the CHM channel editor

Curators can override any auto-derived tag via admin APIs on ContentHub.

## Data flow

```
              WordPress                                YouTube Studio
       (Andrew's editorial team)                (CHM channel editorial)
                 │                                          │
                 │ every publish/update/delete              │ periodic snapshot
                 │ (mu-plugin cht-webhook.php)              │ (post_tagging Lambda)
                 ▼                                          │
       ECS webhook (/api/wordpress)                         │
                 │                                          │
                 │ HMAC verify + enqueue                    │
                 ▼                                          │
              SQS queue                                     │
                 │                                          │
                 │ Lambda drain                             │
                 ▼                                          │
       wordpress_events table                               │
       (categories, tags, YT video ID)                      │
                                                            │
                                                            ▼
                          Clip.tags (yt:<value> namespace, replace-on-write)
                                                            │
                                                            │ cache_clear ('contenthub' scope)
                                                            ▼
                                                     CHT Redis invalidated
                                                     (cht:catalog:*, cht:contenthub:*,
                                                      cht:kol-network:*)

Curator admin edits:
       Admin UI → CHT proxy → ContentHub /api/admin/{clips,playlists}/{id}/tags
       → Clip.tags / PlaylistTag.tags (any namespace)
       → sets tags_curator_override=true (Clip only) so cron passes skip it
       → cache_clear ('contenthub' scope)
```

## Namespaces

Ten recognized namespaces (SCRUM-73 revised). All values are freeform
strings after normalization (no kebab-case enforcement). Namespace is
always lowercased; value is trimmed but otherwise preserved.

### Editorial + curator semantic (7)
| ns | Source | Example values |
|---|---|---|
| `biomarker` | Curator / LLM seed | `biomarker:HER2+`, `biomarker:HER2-low`, `biomarker:HR+` |
| `drug` | Curator / LLM seed | `drug:T-DXd`, `drug:Enhertu` (alias→t-dxd), `drug:sg` |
| `trial` | Curator | `trial:DESTINY-Breast09`, `trial:NCT01234567` |
| `doctor` | `playlist_doctor_tagger` Lambda (auto) | `doctor:Pegram`, `doctor:O'Shaughnessy` |
| `conference` | Curator | `conference:ASCO 2026`, `conference:SABCS 2025` |
| `topic` | LLM seed + WP categories projection | `topic:CNS`, `topic:metastatic breast cancer` |
| `stage` | LLM seed | `stage:mBC`, `stage:EBC`, `stage:resectable` |

### Ingested from external editorial surfaces (2)
| ns | Source | Notes |
|---|---|---|
| `wp` | WordPress `post_tag` taxonomy (freeform) | Projected read-time from `wordpress_events.tags`, not written into Clip.tags |
| `yt` | YouTube `snippet.tags` | Written into `Clip.tags` by `post_tagging` Lambda every 12h |

### Catch-all (1)
| ns | Source |
|---|---|
| `other` | Legacy imports, bare (unprefixed) tags |

## Write paths (who writes what)

| Writer | Reads from | Writes to | Namespaces |
|---|---|---|---|
| `wordpress_ingest` Lambda | mu-plugin webhook via SQS | `wordpress_events` (categories, tags) | N/A (stored raw) |
| `playlist_doctor_tagger` Lambda (daily 04:30 UTC) | YouTube playlist titles | `Clip.tags`, `Post.tags`, `Shoot.doctors[]` | `doctor:*` only |
| `post_tagging` Lambda (12h) | YouTube `videos.list?part=snippet` | `Clip.tags` | `yt:*` only |
| Admin PATCH `/api/admin/clips/{id}/tags` | Curator UI | `Clip.tags` (any) + `tags_curator_override=true` | Any recognized |
| Admin PATCH `/api/admin/playlists/{id}/tags` | Curator UI | `PlaylistTag.tags`, `PlaylistTag.lane` | Any recognized |

## Read paths (how the frontend sees tags)

### `/api/public/tags` — union of all sources

Returns `{namespace: [full_tag, ...]}` grouped by prefix, sorted within
each namespace.

**Data sources:**
1. `Clip.tags` for chm-official clips (all namespaces)
2. `Post.tags` (all namespaces)
3. `wordpress_events.categories` (latest per post, excluding deleted) → `topic:*`
4. `wordpress_events.tags` (same) → `wp:*`

Bare (unprefixed) values fall under `other`.

### `/api/public/clips?tag=` — filter clips

Semantics: **AND across namespaces, OR within a namespace** (SCRUM-77).

Partitioned by namespace source:
- `biomarker:` / `drug:` / `doctor:` / `trial:` / `conference:` / `stage:` /
  `yt:` / `other:` — filter against `Clip.tags` array
- `topic:` / `wp:` — filter via WP join: clip's YouTube video ID must
  map to a `wordpress_events` row whose `categories` (for topic:) or
  `tags` (for wp:) contains the requested value

Mixing works transparently: `?tag=topic:her2,drug:T-DXd` returns clips
whose linked WP post has `her2` in categories AND whose `Clip.tags`
contains `drug:T-DXd`.

### `/api/public/playlists?tag=&lane=` — filter playlists

Same AND/OR semantics on `PlaylistTag.tags`. Lane is a single exact-match
filter (biomarker | drug | trial | doctor_pair | mixed | archive).

## Cache invalidation

All admin writes + `post_tagging` Lambda fire `notify_cht_cache_clear(scope='contenthub')`.
On CHT, that scope expands to `cht:catalog:*`, `cht:contenthub:*`,
`cht:kol-network:*` (see cht-platform-tool `cache-keys.ts`
`cachePatternsForScope`). Sessions never swept.

CHT's Redis cache is invalidated within seconds; React Query on the
frontend has 5-min `staleTime` so curator edits appear on next
page nav / refetch, not real-time.

## What this replaces

- **MediaHub `shoot_tag_distribution`** — deprecated 2026-05-18 (40%
  over-tagging incident). Not migrated to ContentHub per the migration
  plan; would need per-clip LLM classifier if reintroduced.
- **MediaHub `post_tagger`** — was on producer side of MediaHub; the
  ContentHub `post_tagging` Lambda is the replacement scoped to
  `yt:*` namespace only.
- **Regex playlist-title matching** — dead as of SCRUM-79.
  `PlaylistTagOverlay` (curator-set) is the source of truth for
  playlist classification; title regex remains only as a fallback
  for untagged playlists.

## Follow-ups (out of Epic B scope)

- Enable `post_tagging` in tfvars (`sync_jobs_enabled.post_tagging = true`)
- Backfill task: LLM re-run against Clip.title + description + ai_summary
  when new content lands (currently seeded from a one-shot MediaHub dump)
- Distinguish `topic:*` sourced from Clip.tags vs from WP categories at
  the read layer (would require `clip-topic:` / `wp-topic:` split)
- CloudWatch alarms on `post_tagging` Lambda (already scaffolded per
  SCRUM-78 pattern; wire threshold once run cadence is known)
