# services/lambdas/sync/

Per-platform sync Lambdas. Replaces the in-process APScheduler workers from the legacy MediaHub.

## Functions (per migration plan section 7)

| Function | Schedule | Executor | Cache clear |
|---|---|---|---|
| `platform_sync_youtube/` | 12h | SQS+Lambda | Yes |
| `platform_sync_linkedin/` | 12h | SQS+Lambda | Yes |
| `platform_sync_x/` | 12h | SQS+Lambda | Yes |
| `platform_sync_facebook/` | 12h | SQS+Lambda | Yes |
| `platform_sync_instagram/` | 12h | SQS+Lambda | Yes |
| `platform_stats/` | 12h | SQS+Lambda | Yes |
| `ai_summaries/` | 12h | SQS+Lambda | Yes |
| `metric_snapshots/` | 12h | Lambda | No |
| `linkedin_thumbnail_refresh/` | daily 05:00 UTC | Lambda | No |
| `linkedin_post_stats_refresh/` | 12h | Lambda | No |

## Operational notes

- **SQS+Lambda pattern** for any sync job that may batch, retry, or run >5 minutes.
- **Direct Lambda** for fast, per-tick maintenance work.
- **DLQ per queue.** Failed jobs go to a dead-letter queue, alarm fires on DLQ depth > 0.
- **Idempotent handlers.** Re-running a sync over the same window produces the same state.
- **OAuth tokens** for platform APIs live in AWS Secrets Manager. Per-platform token rotation handled by each Lambda.
- **`linkedin_thumbnail_refresh`** is the natural pilot for the EventBridge → Lambda pattern: daily, idempotent, low blast radius.

## Out of scope

- `kol_cache_warm` — drop per migration plan (not migrating).
