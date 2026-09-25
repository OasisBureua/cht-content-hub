# CPR-9 vtt_object_ingest — extra wiring beyond sync_jobs.tf.
#
# The function, reserved concurrency, VPC, and env come from lambda-job.
# This file adds: GetObject-only IAM, async-invoke DLQ (not an SQS trigger),
# and outputs for cht-platform-tool's bucket notification.

locals {
  vtt_object_ingest_enabled = lookup(var.sync_jobs_enabled, "vtt_object_ingest", false)
}

resource "aws_iam_role_policy" "vtt_object_ingest_s3" {
  count = local.vtt_object_ingest_enabled ? 1 : 0

  name = "${local.resource_prefix}-sync-vtt-object-ingest-s3"
  role = module.sync_lambda["vtt_object_ingest"].iam_role_name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "GetObjectZoomRecordingsVtt"
      Effect   = "Allow"
      Action   = ["s3:GetObject"]
      Resource = ["arn:aws:s3:::cht-*-session-assets/zoom-recordings/*"]
    }]
  })
}

resource "aws_sqs_queue" "vtt_object_ingest_async_dlq" {
  count = local.vtt_object_ingest_enabled ? 1 : 0

  name                      = "${local.resource_prefix}-sync-vtt-object-ingest-async-dlq"
  message_retention_seconds = 1209600

  tags = {
    Name        = "${local.resource_prefix}-sync-vtt-object-ingest-async-dlq"
    Environment = var.environment
    Job         = "vtt_object_ingest"
  }
}

resource "aws_iam_role_policy" "vtt_object_ingest_async_dlq" {
  count = local.vtt_object_ingest_enabled ? 1 : 0

  name = "${local.resource_prefix}-sync-vtt-object-ingest-async-dlq"
  role = module.sync_lambda["vtt_object_ingest"].iam_role_name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "SendFailedAsyncInvokesToDlq"
      Effect   = "Allow"
      Action   = ["sqs:SendMessage"]
      Resource = [aws_sqs_queue.vtt_object_ingest_async_dlq[0].arn]
    }]
  })
}

# CPR-29 — Hub owns this. Platform CI cannot AddPermission on our function.
# Platform sets the bucket notification to this Lambda after apply.
resource "aws_lambda_permission" "vtt_object_ingest_s3" {
  count = local.vtt_object_ingest_enabled && var.platform_export_transcript_bucket != "" ? 1 : 0

  statement_id   = "AllowS3SessionAssetsInvokeVttObjectIngest"
  action         = "lambda:InvokeFunction"
  function_name  = module.sync_lambda["vtt_object_ingest"].function_name
  principal      = "s3.amazonaws.com"
  source_arn     = "arn:aws:s3:::${var.platform_export_transcript_bucket}"
  source_account = "233636046512"
}

resource "aws_lambda_function_event_invoke_config" "vtt_object_ingest" {
  count = local.vtt_object_ingest_enabled ? 1 : 0

  function_name                = module.sync_lambda["vtt_object_ingest"].function_name
  maximum_retry_attempts       = 2
  maximum_event_age_in_seconds = 3600

  destination_config {
    on_failure {
      destination = aws_sqs_queue.vtt_object_ingest_async_dlq[0].arn
    }
  }

  depends_on = [aws_iam_role_policy.vtt_object_ingest_async_dlq]
}

output "vtt_object_ingest_lambda_arn" {
  description = "Hub Lambda ARN for platform-tool S3 notify (prefix zoom-recordings/, suffix .vtt)"
  value       = try(module.sync_lambda["vtt_object_ingest"].function_arn, null)
}

output "vtt_object_ingest_lambda_name" {
  description = "Hub Lambda function name for vtt_object_ingest"
  value       = try(module.sync_lambda["vtt_object_ingest"].function_name, null)
}

output "vtt_object_ingest_async_dlq_arn" {
  description = "Async-invoke DLQ for failed S3 → Lambda deliveries"
  value       = try(aws_sqs_queue.vtt_object_ingest_async_dlq[0].arn, null)
}

output "platform_export_transcript_bucket" {
  description = "Session-assets bucket this Lambda reads (must match platform-tool notify bucket)"
  value       = var.platform_export_transcript_bucket
}
