# CPR-41 — S3 GetObject for Platform Zoom VTTs during export-ingest.
# API ECS and the platform_export_ingest Lambda both need this when
# PLATFORM_EXPORT_TRANSCRIPT_BUCKET is set (same pattern as vtt_object_ingest).

locals {
  platform_export_ingest_enabled = lookup(var.sync_jobs_enabled, "platform_export_ingest", false)
  platform_export_transcript_s3_enabled = var.platform_export_transcript_bucket != ""
}

resource "aws_iam_role_policy" "platform_export_ingest_s3" {
  count = local.platform_export_ingest_enabled && local.platform_export_transcript_s3_enabled ? 1 : 0

  name = "${local.resource_prefix}-sync-platform-export-ingest-s3"
  role = module.sync_lambda["platform_export_ingest"].iam_role_name
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

resource "aws_iam_role_policy" "api_platform_export_transcript_s3" {
  count = local.platform_export_transcript_s3_enabled ? 1 : 0

  name = "${local.resource_prefix}-api-platform-export-transcript-s3"
  role = module.iam.task_role_name
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
