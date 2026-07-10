# WordPress ingest — extra wiring beyond what sync_jobs.tf provides.
#
# The Lambda consumer + its SQS queue + IAM read-from-SQS + RDS ingress
# are all created by the sync_jobs.tf module instantiation with
# `sqs_trigger = true` (via the shared `rds_from_sync_lambda` for_each).
#
# The ALB security group ingress for Andrew's WordPress egress IP(s) is
# passed into the alb_api module in main.tf via `wordpress_ingress_cidr_blocks`
# (concatenated with cht_nat_gateway_cidr_blocks).
#
# What's left here: outputs for verification during dev deploys.

output "wordpress_ingest_queue_url" {
  description = "SQS queue URL for WordPress webhook events (ECS route → this queue → Lambda)"
  value       = try(module.sync_lambda["wordpress_ingest"].sqs_queue_url, null)
}

output "wordpress_ingest_queue_arn" {
  description = "SQS queue ARN for WordPress webhook events"
  value       = try(module.sync_lambda["wordpress_ingest"].sqs_queue_arn, null)
}

# ─────────────────────────────────────────────────────────────────────────────
# CloudWatch alarms
# ─────────────────────────────────────────────────────────────────────────────
# Kept minimal for the POC: DLQ depth (real failures) + Lambda errors
# (transient issues). No SNS wiring yet — alarms surface in the console
# and via CloudWatch dashboards. Add SNS notify_arn later if the ops
# rotation needs push notifications.

locals {
  wordpress_ingest_lambda_name = try(
    "${var.project}${contains(["prod", "platform"], var.environment) ? "" : "-${var.environment}"}-sync-wordpress-ingest",
    null,
  )
  wordpress_ingest_queue_name = try(module.sync_lambda["wordpress_ingest"].sqs_queue_url, "")
}

# DLQ depth — any messages here mean something failed 3× in a row.
resource "aws_cloudwatch_metric_alarm" "wordpress_ingest_dlq_depth" {
  count = lookup(var.sync_jobs_enabled, "wordpress_ingest", false) ? 1 : 0

  alarm_name          = "${local.resource_prefix}-wordpress-ingest-dlq-depth"
  alarm_description   = "Messages in the WordPress ingest DLQ — investigate failed Lambda invocations"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 300
  statistic           = "Maximum"
  threshold           = 0
  treat_missing_data  = "notBreaching"

  dimensions = {
    QueueName = "${local.resource_prefix}-sync-wordpress-ingest-dlq"
  }

  tags = {
    Purpose = "wordpress-ingest-dlq-depth"
  }
}

# Lambda errors — nonzero over 5 min is worth a look.
resource "aws_cloudwatch_metric_alarm" "wordpress_ingest_lambda_errors" {
  count = lookup(var.sync_jobs_enabled, "wordpress_ingest", false) ? 1 : 0

  alarm_name          = "${local.resource_prefix}-wordpress-ingest-lambda-errors"
  alarm_description   = "WordPress ingest Lambda invocation errors (5xx from consumer)"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = 0
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = "${local.resource_prefix}-sync-wordpress-ingest"
  }

  tags = {
    Purpose = "wordpress-ingest-lambda-errors"
  }
}
