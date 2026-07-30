# Sync Lambda jobs — same module + artifact per environment (separate function instances).

locals {
  sync_lambda_package = var.sync_lambda_package_path != "" ? var.sync_lambda_package_path : abspath("${path.module}/../../../../dist/sync-lambda.zip")

  sync_jobs = {
    cache_clear = {
      enabled                        = lookup(var.sync_jobs_enabled, "cache_clear", true)
      handler                        = "jobs.cache_clear.handler.handler"
      timeout                        = 60
      memory_size                    = 256
      schedule_expression            = null
      sqs_trigger                    = false
      reserved_concurrent_executions = -1
    }
    hcp_intel_poll = {
      enabled                        = lookup(var.sync_jobs_enabled, "hcp_intel_poll", true)
      handler                        = "jobs.hcp_intel_poll.handler.handler"
      timeout                        = 900
      memory_size                    = 1024
      schedule_expression            = "rate(30 minutes)"
      sqs_trigger                    = true
      reserved_concurrent_executions = 1
    }
    openalex_backfill = {
      enabled                        = lookup(var.sync_jobs_enabled, "openalex_backfill", true)
      handler                        = "jobs.openalex_backfill.handler.handler"
      timeout                        = 900
      memory_size                    = 1024
      schedule_expression            = "cron(30 3 ? * SUN *)"
      sqs_trigger                    = false
      reserved_concurrent_executions = 1
    }
    kol_hcp_matcher = {
      enabled                        = lookup(var.sync_jobs_enabled, "kol_hcp_matcher", true)
      handler                        = "jobs.kol_hcp_matcher.handler.handler"
      timeout                        = 300
      memory_size                    = 512
      schedule_expression            = "cron(0 4 * * ? *)"
      sqs_trigger                    = false
      reserved_concurrent_executions = 1
    }
    post_tagging = {
      enabled                        = lookup(var.sync_jobs_enabled, "post_tagging", false)
      handler                        = "jobs.post_tagging.handler.handler"
      timeout                        = 900
      memory_size                    = 1024
      schedule_expression            = "rate(12 hours)"
      sqs_trigger                    = false
      reserved_concurrent_executions = 1
    }
    playlist_doctor_tagger = {
      enabled                        = lookup(var.sync_jobs_enabled, "playlist_doctor_tagger", false)
      handler                        = "jobs.playlist_doctor_tagger.handler.handler"
      timeout                        = 900
      memory_size                    = 1024
      schedule_expression            = "cron(30 4 * * ? *)"
      sqs_trigger                    = false
      reserved_concurrent_executions = 1
    }
    wordpress_ingest = {
      enabled                        = lookup(var.sync_jobs_enabled, "wordpress_ingest", false)
      handler                        = "jobs.wordpress_ingest.handler.handler"
      timeout                        = 60
      memory_size                    = 512
      schedule_expression            = null
      sqs_trigger                    = true
      reserved_concurrent_executions = -1
    }
    # One-shot: restore mediahub prod clips + posts + shoots into contenthub RDS.
    # Manual invoke only. Idempotent (skips if `clips` already has ≥100 rows).
    # 900s timeout for the ~12MB SQL apply; 1024MB memory sized for asyncpg + SQL string.
    clips_seed = {
      enabled                        = lookup(var.sync_jobs_enabled, "clips_seed", false)
      handler                        = "jobs.clips_seed.handler.handler"
      timeout                        = 900
      memory_size                    = 1024
      schedule_expression            = null
      sqs_trigger                    = false
      reserved_concurrent_executions = 1
    }
    # One-shot: for wordpress_events rows ingested before mu-plugin v0.2 (which
    # extracts youtube_video_id + featured_media_url server-side), fetch each
    # post via WP REST and UPDATE the row. Idempotent — WHERE youtube_video_id
    # IS NULL. Rate-limited 4 req/sec (250ms sleep) to be polite with WP + WAF.
    # 900s timeout supports ~3.5k posts per invocation; batch_size caps per-run.
    wordpress_backfill = {
      enabled                        = lookup(var.sync_jobs_enabled, "wordpress_backfill", false)
      handler                        = "jobs.wordpress_backfill.handler.handler"
      timeout                        = 900
      memory_size                    = 512
      schedule_expression            = null
      sqs_trigger                    = false
      reserved_concurrent_executions = 1
    }
    # One-shot: page through WP REST /posts and INSERT into wordpress_events
    # for the entire editorial catalog. Idempotent via UNIQUE (post_id,
    # modified_gmt) — re-runs are no-ops for rows that exist. Runs at
    # 1 req/sec (same cadence as backfill). 900s supports the full catalog
    # (~500 posts / ~5 pages / ~8 min) with margin for vocab fetches.
    wordpress_seed = {
      enabled                        = lookup(var.sync_jobs_enabled, "wordpress_seed", false)
      handler                        = "jobs.wordpress_seed.handler.handler"
      timeout                        = 900
      memory_size                    = 512
      schedule_expression            = null
      sqs_trigger                    = false
      reserved_concurrent_executions = 1
    }
    # One-shot: hydrate Layer 2 projected-state tables (wordpress_posts +
    # wordpress_series + wordpress_categories + wordpress_tags + M:M
    # association tables) from WP REST. Fetches term inventories first
    # (name / description / parent / term_id), then post membership arrays,
    # feeds both into the shared projection module — same code path the
    # real-time ingest Lambda uses. Idempotent by construction (UPSERT +
    # set-based M:M reconcile). Runs at 1 req/sec.
    #
    # Also serves as the drift-catch-up path: re-invoking on a schedule
    # covers any webhook events that got dropped between mu-plugin fire and
    # SQS enqueue (though ideally WPR-17 reconcile handles that).
    wordpress_projection_backfill = {
      enabled                        = lookup(var.sync_jobs_enabled, "wordpress_projection_backfill", false)
      handler                        = "jobs.wordpress_projection_backfill.handler.handler"
      timeout                        = 900
      memory_size                    = 512
      schedule_expression            = null
      sqs_trigger                    = false
      reserved_concurrent_executions = 1
    }
    # WPR-11 tag-namespace seed Lambda. Runs the rulebook against every
    # WP tag in wordpress_tags (Layer 2) and populates wp_tag_namespace_map.
    # Idempotent: preserves curator-sourced rows, only touches rule-sourced
    # or absent entries. Re-run whenever the rulebook itself changes
    # (with overwrite_rules=true) or after new WP tags land.
    wp_tag_namespace_seed = {
      enabled                        = lookup(var.sync_jobs_enabled, "wp_tag_namespace_seed", false)
      handler                        = "jobs.wp_tag_namespace_seed.handler.handler"
      timeout                        = 300
      memory_size                    = 512
      schedule_expression            = null
      sqs_trigger                    = false
      reserved_concurrent_executions = 1
    }
    # WPR-6 fuzzy-match Lambda. Scores every (playlist, series) pair using
    # doctor-surname overlap + title similarity, inserts pending review
    # rows for candidates ≥0.5. Curator (Morgan / Sebastien) approves or
    # rejects via /api/admin/playlist-series-review endpoints. On approval,
    # `playlist_tags.wp_series_slug` gets set atomically.
    #
    # Manual-invoke by default. Safe to schedule if we want re-scoring on
    # a cadence (e.g., weekly for new playlists) — but idempotent so
    # re-runs against unchanged data are cheap no-ops.
    wordpress_series_playlist_match = {
      enabled                        = lookup(var.sync_jobs_enabled, "wordpress_series_playlist_match", false)
      handler                        = "jobs.wordpress_series_playlist_match.handler.handler"
      timeout                        = 900
      memory_size                    = 512
      schedule_expression            = null
      sqs_trigger                    = false
      reserved_concurrent_executions = 1
    }
    # Daily standing production defense (WPR-17 / SCRUM-168). Diffs WP REST
    # against Layer 2 wordpress_posts + wordpress_series/_categories/_tags.
    # For any CH-side row not present on WP, emits a signed synthetic
    # webhook (`deleted` for posts, `term_deleted` for terms) at our own
    # ingress — the ingest Lambda applies the tombstone through the normal
    # projection path. Idempotent by construction.
    #
    # Bounds mirror drift to 24h even if the mu-plugin misses a webhook
    # for a transient network reason. Alarm fires (CloudWatch metric) if
    # drift exceeds threshold BEFORE reconciliation runs — that indicates
    # the mu-plugin is broken, not just one dropped event.
    wordpress_reconcile = {
      enabled                        = lookup(var.sync_jobs_enabled, "wordpress_reconcile", false)
      handler                        = "jobs.wordpress_reconcile.handler.handler"
      timeout                        = 900
      memory_size                    = 512
      # Daily 03:00 UTC (23:00 US-East summer time — avoids the peak
      # editorial-edit window and Andrew's own workflow hours).
      schedule_expression            = "cron(0 3 * * ? *)"
      sqs_trigger                    = false
      reserved_concurrent_executions = 1
    }
  }
}

locals {
  # Per-job extra environment variables. `wordpress_reconcile` needs its
  # own ingress URL (same host the mu-plugin hits) so it can emit signed
  # synthetic delete webhooks. The self-URL is derived from the ECS route
  # ALB endpoint, which lives in var.wordpress_webhook_self_url on the
  # environment tfvars — empty string on dev falls back to the module
  # default (no synthetic emission, drift-only reporting).
  sync_job_extra_env = {
    wordpress_reconcile = merge(
      var.wordpress_webhook_self_url != "" ? { SELF_WEBHOOK_URL = var.wordpress_webhook_self_url } : {},
      { WP_BASE_URL = var.wordpress_base_url }
    )
    wordpress_projection_backfill = {
      WP_BASE_URL = var.wordpress_base_url
    }
    wordpress_seed = {
      WP_BASE_URL = var.wordpress_base_url
    }
    wordpress_backfill = {
      WP_BASE_URL = var.wordpress_base_url
    }
  }
}

module "sync_lambda" {
  for_each = { for name, cfg in local.sync_jobs : name => cfg if cfg.enabled }

  source = "../../modules/compute/lambda-job"

  project                        = var.project
  environment                    = var.environment
  aws_region                     = "us-east-1"
  job_name                       = each.key
  handler                        = each.value.handler
  deployment_package_path        = local.sync_lambda_package
  timeout                        = each.value.timeout
  memory_size                    = each.value.memory_size
  schedule_expression            = each.value.schedule_expression
  sqs_trigger                    = each.value.sqs_trigger
  reserved_concurrent_executions = each.value.reserved_concurrent_executions
  vpc_id                         = var.vpc_id
  private_subnet_ids             = var.private_subnet_ids
  database_secret_arn            = local.database_secret_arn
  app_secrets_arn                = module.app_secrets.app_secrets_arn
  cht_cache_clear_url            = var.cht_cache_clear_url
  log_retention_days             = local.log_retention
  enabled                        = true

  # Per-job env vars. Merged with the module's default env; module defaults
  # win on collision. wordpress_reconcile needs its own ingress URL so it
  # can fire synthetic HMAC-signed webhooks at the ECS route.
  extra_env = lookup(local.sync_job_extra_env, each.key, {})

  depends_on = [module.app_secrets]
}

resource "aws_vpc_security_group_ingress_rule" "rds_from_sync_lambda" {
  for_each = module.sync_lambda

  description                  = "PostgreSQL from sync Lambda ${each.key}"
  security_group_id            = local.database_security_group_id
  referenced_security_group_id = each.value.security_group_id
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
}
