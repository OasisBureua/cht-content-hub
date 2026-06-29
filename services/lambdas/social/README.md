# services/lambdas/social/

Lambdas for social platform publishing. Per-platform workers are the preferred decomposition shape over a shared social-sync worker.

Expected functions:

- `linkedin_stats_sync/` — periodic org stats refresh
- `linkedin_posts_sync/` — periodic post discovery
- `linkedin_thumbnail_refresh/` — daily thumbnail URL refresh (pilot candidate — small, daily, idempotent)
- `linkedin_ads_sync/` — daily campaign sync
- `linkedin_post_stats_refresh/` — twice-daily post-stat refresh
- `youtube_stats_sync/`
- `youtube_posts_sync/`
- `youtube_unlisted_sync/`
- `facebook_posts_sync/`
- `instagram_posts_sync/`
- `x_stats_sync/`
- `x_posts_sync/`
- `metric_snapshots/` — account-level metric snapshots
