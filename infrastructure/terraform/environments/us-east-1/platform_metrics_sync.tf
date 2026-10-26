# CPR-15 — alarms for the daily platform_metrics_sync Lambda.
# The job returns "partial" instead of failing when a source errors, so the
# Lambda Errors metric stays at zero; these alarms read its log lines instead.
# No SNS wiring yet (same as wordpress_ingest): alarms surface in the console.

locals {
  platform_metrics_sync_enabled = lookup(var.sync_jobs_enabled, "platform_metrics_sync", false)
  platform_metrics_sync_log     = "/aws/lambda/${local.resource_prefix}-sync-platform-metrics-sync"
  platform_metrics_namespace    = "ContentHub/${var.environment}"
}

resource "aws_cloudwatch_log_metric_filter" "linkedin_ads_token_expiring" {
  count = local.platform_metrics_sync_enabled ? 1 : 0

  name           = "${local.resource_prefix}-linkedin-ads-token-expiring"
  log_group_name = local.platform_metrics_sync_log
  pattern        = "linkedin_ads_token_expiring"

  metric_transformation {
    name      = "LinkedInAdsTokenExpiring"
    namespace = local.platform_metrics_namespace
    value     = "1"
  }

  depends_on = [module.sync_lambda]
}

resource "aws_cloudwatch_metric_alarm" "linkedin_ads_token_expiring" {
  count = local.platform_metrics_sync_enabled ? 1 : 0

  alarm_name          = "${local.resource_prefix}-linkedin-ads-token-expiring"
  alarm_description   = "LinkedIn Ads refresh token expires within LINKEDIN_ADS_TOKEN_WARN_DAYS. Re-authorize (cpr49-test-kit kit/linkedin_ads_auth.py) and update LINKEDIN_ADS_REFRESH_TOKEN."
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "LinkedInAdsTokenExpiring"
  namespace           = local.platform_metrics_namespace
  period              = 86400
  statistic           = "Sum"
  threshold           = 1
  treat_missing_data  = "notBreaching"

  tags = {
    Purpose = "linkedin-ads-token-expiring"
  }
}

resource "aws_cloudwatch_log_metric_filter" "platform_metrics_sync_errors" {
  count = local.platform_metrics_sync_enabled ? 1 : 0

  name           = "${local.resource_prefix}-platform-metrics-sync-errors"
  log_group_name = local.platform_metrics_sync_log
  pattern        = "platform_metrics_sync_errors"

  metric_transformation {
    name      = "PlatformMetricsSyncErrors"
    namespace = local.platform_metrics_namespace
    value     = "1"
  }

  depends_on = [module.sync_lambda]
}

resource "aws_cloudwatch_metric_alarm" "platform_metrics_sync_errors" {
  count = local.platform_metrics_sync_enabled ? 1 : 0

  alarm_name          = "${local.resource_prefix}-platform-metrics-sync-errors"
  alarm_description   = "The daily social sync had a source error (YouTube or LinkedIn Ads). See the Lambda log and platform_sync_runs."
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "PlatformMetricsSyncErrors"
  namespace           = local.platform_metrics_namespace
  period              = 86400
  statistic           = "Sum"
  threshold           = 1
  treat_missing_data  = "notBreaching"

  tags = {
    Purpose = "platform-metrics-sync-errors"
  }
}
