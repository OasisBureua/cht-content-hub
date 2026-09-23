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
    # WordPress mirror ops — SINGLE Lambda dispatching to 6 modes via
    # event["op"]. Consolidated from what would otherwise be six separate
    # Lambdas (per review guidance on Lambda sprawl), all sharing the
    # WordPress domain + same trigger profile + same memory footprint +
    # same auth path.
    #
    #   Layer 1 (event log) ops:
    #     - seed_events         (manual): one-shot ingest all published
    #       WP posts into wordpress_events. Idempotent via UNIQUE constraint.
    #     - backfill_events     (manual): fill youtube_video_id +
    #       featured_media_url on pre-v0.2 rows.
    #
    #   Layer 2 (projected state) ops:
    #     - backfill_projection (manual): hydrate Layer 2 tables from WP REST.
    #     - match_series_playlists (manual): WPR-6 fuzzy-match, insert
    #       pending review rows. Curator approves/rejects via admin endpoint.
    #     - seed_tag_namespace  (manual): WPR-11, run rulebook against
    #       wordpress_tags, UPSERT wp_tag_namespace_map.
    #
    #   Standing defense:
    #     - reconcile_drift     (DAILY CRON DEFAULT): WPR-17. Diffs WP REST
    #       vs Layer 2, emits signed synthetic delete webhooks for phantoms.
    #       CloudWatch drift alarm.
    #
    # Each op module lives at backend/src/jobs/wordpress_projection_ops/<op>.py.
    # Dispatcher + registry at backend/src/jobs/wordpress_projection_ops/__init__.py.
    # Lambda entry point at sync/jobs/wordpress_projection_ops/handler.py.
    #
    # Daily 03:00 UTC (23:00 US-East summer time — avoids peak editorial
    # window). Cron fires with no payload → dispatcher defaults to
    # reconcile_drift. Manual invokes pass {"op": "..."} for other modes.
    #
    # Not folded in here (deliberately): `wordpress_ingest` — SQS-triggered
    # hot path for WP webhooks, different scale profile.
    wordpress_projection_ops = {
      enabled                        = lookup(var.sync_jobs_enabled, "wordpress_projection_ops", false)
      handler                        = "jobs.wordpress_projection_ops.handler.handler"
      timeout                        = 900
      memory_size                    = 512
      schedule_expression            = "cron(0 3 * * ? *)"
      sqs_trigger                    = false
      reserved_concurrent_executions = 1
    }
  }
}

locals {
  # Per-job extra environment variables. `wordpress_projection_ops` needs
  # its own ingress URL (same host the mu-plugin hits) so its reconcile_drift
  # op can emit signed synthetic delete webhooks. Empty string on dev falls
  # back to drift-only reporting (no synthetic emission). All ops that hit
  # WordPress REST also need the base URL.
  sync_job_extra_env = {
    wordpress_projection_ops = merge(
      var.wordpress_webhook_self_url != "" ? { SELF_WEBHOOK_URL = var.wordpress_webhook_self_url } : {},
      { WP_BASE_URL = var.wordpress_base_url }
    )
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
