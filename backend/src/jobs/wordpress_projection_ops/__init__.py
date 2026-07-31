"""wordpress_projection_ops — dispatcher registry for all WordPress-domain ops.

Six ops live as sibling modules in this package, all sharing this single
Lambda deployment. Each exposes a `run(event)` coroutine. The dispatcher
(below) routes on event["op"]:

  Layer 1 (event log) ops:
    - "seed_events"            → one-shot ingest all published WP posts
    - "backfill_events"        → fill youtube_video_id + featured_media_url
                                 on pre-v0.2 wordpress_events rows

  Layer 2 (projected state) ops:
    - "backfill_projection"    → one-shot hydration of Layer 2 tables from WP REST
    - "match_series_playlists" → fuzzy-match YT playlists to WP series (WPR-6)
    - "seed_tag_namespace"     → run rulebook against WP tags (WPR-11)

  Standing defense:
    - "reconcile_drift"        → daily cron; diffs WP vs CH, emits synthetic
                                 delete webhooks for phantoms (WPR-17)

Consolidated from what would otherwise be six separate Lambdas into one,
per review guidance on Lambda sprawl. All ops share the same domain
(WordPress mirror), same trigger profile (manual + daily cron), same
memory profile (~512MB), and mostly the same auth path (WordPress App
Password from Secrets Manager).

Each op still gets its own structured log output (via distinct logger
names) so CloudWatch queries stay clean per-op.

Trigger:
- The daily EventBridge cron fires this Lambda with no payload override.
  Dispatcher default routes to `reconcile_drift` (the standing-defense op).
- All other ops are manual-invoke:
    aws lambda invoke \\
      --function-name contenthub-dev-sync-wordpress-projection-ops \\
      --payload '{"op": "backfill_projection"}' \\
      /tmp/resp.json && cat /tmp/resp.json

Not consolidated here (deliberately):
- `wordpress_ingest` — SQS-triggered hot path for WP webhooks. Different
  trigger profile (event-driven, must scale for burst editorial activity).
  Consolidating would break its per-webhook latency profile.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from jobs.wordpress_projection_ops import (
    backfill_events,
    backfill_projection,
    match_series_playlists,
    reconcile_drift,
    seed_events,
    seed_tag_namespace,
)

# Registry — the dispatcher looks up event["op"] here. Explicit rather
# than dynamic import so any typo in an op name fails at review time,
# not at prod runtime.
OP_REGISTRY: dict[str, Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]] = {
    "seed_events": seed_events.run,
    "backfill_events": backfill_events.run,
    "backfill_projection": backfill_projection.run,
    "match_series_playlists": match_series_playlists.run,
    "seed_tag_namespace": seed_tag_namespace.run,
    "reconcile_drift": reconcile_drift.run,
}


async def dispatch(event: dict[str, Any]) -> dict[str, Any]:
    """Route a single event to the appropriate op's run() coroutine.

    Reads event["op"], falls back to "reconcile_drift" so the daily
    EventBridge cron (which fires without a payload override) hits the
    standing-defense op by default.
    """
    op_name = event.get("op") or "reconcile_drift"
    op_fn = OP_REGISTRY.get(op_name)
    if op_fn is None:
        return {
            "status": "error",
            "reason": f"unknown op: {op_name!r}",
            "valid_ops": sorted(OP_REGISTRY.keys()),
        }
    return await op_fn(event)
