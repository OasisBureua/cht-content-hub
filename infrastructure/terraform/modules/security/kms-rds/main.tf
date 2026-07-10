locals {
  prefix = var.name_prefix
}

resource "aws_kms_key" "rds" {
  description             = "${local.prefix} RDS encryption key (DR region)"
  deletion_window_in_days = var.deletion_window_in_days
  enable_key_rotation     = true

  tags = {
    Name        = "${local.prefix}-rds-key"
    Service     = "rds"
  }
}

resource "aws_kms_alias" "rds" {
  name          = "alias/${local.prefix}-rds"
  target_key_id = aws_kms_key.rds.key_id
}
