locals {
  prefix      = contains(["prod", "platform"], var.environment) ? var.project : "${var.project}-${var.environment}"
  bucket_name = "${local.prefix}-assets-${var.aws_account_id}"
}

resource "aws_s3_bucket" "assets" {
  bucket = local.bucket_name
}

resource "aws_s3_bucket_public_access_block" "assets" {
  bucket = aws_s3_bucket.assets.id

  block_public_acls       = false
  block_public_policy     = false
  ignore_public_acls      = false
  restrict_public_buckets = false
}

resource "aws_s3_bucket_ownership_controls" "assets" {
  bucket = aws_s3_bucket.assets.id

  rule {
    object_ownership = "BucketOwnerPreferred"
  }
}

resource "aws_s3_bucket_versioning" "assets" {
  bucket = aws_s3_bucket.assets.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "assets" {
  bucket = aws_s3_bucket.assets.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_cors_configuration" "assets" {
  bucket = aws_s3_bucket.assets.id

  cors_rule {
    allowed_headers = ["*"]
    allowed_methods = ["GET", "HEAD"]
    allowed_origins = ["*"]
    expose_headers  = ["ETag"]
    max_age_seconds = 3600
  }
}

data "aws_iam_policy_document" "assets_public_read" {
  statement {
    sid    = "PublicReadKolHeadshots"
    effect = "Allow"
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    actions   = ["s3:GetObject"]
    resources = [for p in var.public_read_prefixes : "${aws_s3_bucket.assets.arn}/${p}*"]
  }
}

resource "aws_s3_bucket_policy" "assets" {
  depends_on = [aws_s3_bucket_public_access_block.assets]

  bucket = aws_s3_bucket.assets.id
  policy = data.aws_iam_policy_document.assets_public_read.json
}

data "aws_iam_policy_document" "task_rw" {
  count = var.attach_task_role_policy ? 1 : 0

  statement {
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
      "s3:ListBucket",
    ]
    resources = [
      aws_s3_bucket.assets.arn,
      "${aws_s3_bucket.assets.arn}/*",
    ]
  }
}

resource "aws_iam_role_policy" "task_assets" {
  count = var.attach_task_role_policy ? 1 : 0

  name   = "${local.prefix}-s3-assets"
  role   = replace(var.task_role_arn, "/^arn:aws:iam::[0-9]+:role\\//", "")
  policy = data.aws_iam_policy_document.task_rw[0].json
}
