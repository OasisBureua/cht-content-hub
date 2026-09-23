"""wordpress_projection_ops — single Lambda handler for all WP mirror ops.

Thin Lambda entry point. All routing + business logic lives in
`backend/src/jobs/wordpress_projection_ops/` — this file just wires the
Lambda runtime (path setup, logging, async event loop) to the dispatcher.

Consolidates what would otherwise be 4 separate Lambdas (reconcile,
backfill, match, tag-seed) into 1, dispatching on event["op"]. See
`backend/src/jobs/wordpress_projection_ops/__init__.py` for the op
registry.

Event shape:
    {
      "op": "reconcile_drift" | "backfill_projection"
          | "match_series_playlists" | "seed_tag_namespace",
      ...op-specific fields...
    }

If `op` is absent, defaults to "reconcile_drift" (the daily-cron use
case). Unknown ops return an error payload listing valid choices.

Scheduling:
- EventBridge cron fires this Lambda daily at 03:00 UTC with the default
  (reconcile_drift) op. Configured in TF, not here.
- All other ops are manual-invoke:
    aws lambda invoke \\
      --function-name contenthub-dev-sync-wordpress-projection-ops \\
      --payload '{"op": "backfill_projection"}' \\
      /tmp/resp.json && cat /tmp/resp.json
"""

from __future__ import annotations

from shared.runtime import configure_logging, install_paths, run_async


async def _run(event: dict) -> dict:
    from jobs.wordpress_projection_ops import dispatch

    return await dispatch(event or {})


def handler(event: dict, context) -> dict:
    install_paths()
    configure_logging()
    return run_async(_run(event or {}))
