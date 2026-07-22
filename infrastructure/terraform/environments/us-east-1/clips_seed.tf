# clips_seed — S3 read policy on the sync Lambda's IAM role so it can pull the
# pg_dump SQL file from the assets bucket. Manual invocation only; when enabled,
# the Lambda is created by the shared sync_jobs.tf module instantiation.

resource "aws_iam_role_policy" "clips_seed_s3_read" {
  count = lookup(var.sync_jobs_enabled, "clips_seed", false) ? 1 : 0

  name = "${local.resource_prefix}-sync-clips-seed-s3-read"
  role = module.sync_lambda["clips_seed"].iam_role_name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["s3:GetObject", "s3:ListBucket"]
      Resource = [
        module.s3_assets.bucket_arn,
        "${module.s3_assets.bucket_arn}/seeds/*",
      ]
    }]
  })
}

output "clips_seed_lambda_name" {
  description = "Function name for `aws lambda invoke` when seeding clip data"
  value       = try(module.sync_lambda["clips_seed"].function_name, null)
}
