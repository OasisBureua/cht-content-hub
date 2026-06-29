# services/lambdas/tagging/

Content tagging Lambdas.

## Functions

- `post_tagger/` — invoked on post upload + per `cache_clear` writes. Runs `scan_text_for_tags` over post text. The `post_tagger` core logic distributes as a **Lambda Layer** so every consumer Lambda imports the same version.
- `playlist_doctor_tagger/` — daily cron at 04:30 UTC. Ingests YouTube playlist titles, writes `doctor:` tags through to clips and posts.

## Out of scope

- `shoot_tag_derivation` / `shoot_tag_distribution` — dormant per migration plan. Do not migrate until product decision.

## Operational notes

- **Reserved concurrency = 1** on both functions. Tag writes are not safe under concurrent invocations.
- Idempotent: re-running over the same post produces the same tag set.
- After successful writes, invoke `cache_clear` to evict CHT-side catalog cache (`cht:catalog:*`).
