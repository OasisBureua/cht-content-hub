locals {
  prefix = contains(["prod", "platform"], var.environment) ? var.project : "${var.project}-${var.environment}"
  name   = var.role == "primary" ? "${local.prefix}-aurora-primary" : "${local.prefix}-aurora-secondary"

  # IAM roles are account-global; primary creates once, secondary references the prod primary role.
  enhanced_monitoring_role_name = var.enhanced_monitoring_role_name != "" ? var.enhanced_monitoring_role_name : (
    var.role == "secondary" ? "${var.project}-aurora-enhanced-monitoring" : "${local.prefix}-aurora-enhanced-monitoring"
  )
}

resource "aws_db_subnet_group" "aurora" {
  name       = "${local.name}-subnet"
  subnet_ids = var.private_subnet_ids

  tags = {
    Name        = "${local.name}-subnet"
    Environment = var.environment
  }
}

resource "aws_security_group" "aurora" {
  name        = "${local.name}-sg"
  description = "Security group for Aurora Global (${var.role})"
  vpc_id      = var.vpc_id

  # Ingress is managed by environment-level aws_vpc_security_group_ingress_rule
  # resources (avoids Terraform cycles with ECS). Match modules/database/rds.
  dynamic "ingress" {
    for_each = length(var.allowed_security_groups) > 0 ? [1] : []
    content {
      description     = "PostgreSQL from ECS tasks"
      from_port       = 5432
      to_port         = 5432
      protocol        = "tcp"
      security_groups = var.allowed_security_groups
    }
  }

  egress {
    description = "Allow all outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "${local.name}-sg"
    Environment = var.environment
  }
}

resource "random_password" "master" {
  count = var.role == "primary" ? 1 : 0

  length           = 32
  special          = true
  override_special = "!#$%&*()-_=+[]{}<>:?"
}

resource "aws_rds_cluster_parameter_group" "aurora" {
  count = var.role == "primary" ? 1 : 0

  name        = "${local.prefix}-aurora-postgres15"
  family      = "aurora-postgresql15"
  description = "Aurora PostgreSQL 15 cluster parameters for ${local.prefix}"

  parameter {
    name  = "log_connections"
    value = "1"
  }

  parameter {
    name  = "log_disconnections"
    value = "1"
  }

  parameter {
    name  = "log_statement"
    value = "all"
  }

  tags = {
    Name        = "${local.prefix}-aurora-params"
    Environment = var.environment
  }
}

resource "aws_rds_global_cluster" "this" {
  count = var.role == "primary" ? 1 : 0

  global_cluster_identifier = "${local.prefix}-global"
  engine                    = "aurora-postgresql"
  engine_version            = var.engine_version
  storage_encrypted         = true
  deletion_protection       = var.deletion_protection
}

resource "aws_rds_cluster" "this" {
  cluster_identifier = local.name
  engine             = "aurora-postgresql"
  engine_version     = var.engine_version
  engine_mode        = "provisioned"

  global_cluster_identifier = var.role == "primary" ? aws_rds_global_cluster.this[0].id : var.global_cluster_identifier

  database_name   = var.role == "primary" ? var.database_name : null
  master_username = var.role == "primary" ? var.master_username : null
  master_password = var.role == "primary" ? random_password.master[0].result : null

  db_subnet_group_name   = aws_db_subnet_group.aurora.name
  vpc_security_group_ids = [aws_security_group.aurora.id]
  kms_key_id             = var.kms_key_arn != "" ? var.kms_key_arn : null
  storage_encrypted      = true

  backup_retention_period      = var.backup_retention_period
  preferred_backup_window      = "03:00-04:00"
  preferred_maintenance_window = "mon:04:00-mon:05:00"

  deletion_protection                 = var.deletion_protection
  skip_final_snapshot                 = !contains(["prod", "platform"], var.environment)
  final_snapshot_identifier           = contains(["prod", "platform"], var.environment) ? "${local.name}-final" : null
  enabled_cloudwatch_logs_exports     = ["postgresql"]
  copy_tags_to_snapshot               = true
  iam_database_authentication_enabled = var.iam_database_authentication_enabled

  db_cluster_parameter_group_name = var.role == "primary" ? aws_rds_cluster_parameter_group.aurora[0].name : null

  lifecycle {
    ignore_changes = [
      master_password,
      # AWS sets these on global secondary members; Terraform must not "correct"
      # them on later applies or the cluster is detached from the global DB.
      global_cluster_identifier,
      replication_source_identifier,
    ]
  }
}

resource "aws_iam_role" "enhanced_monitoring" {
  count = var.enhanced_monitoring_interval > 0 && var.role == "primary" ? 1 : 0

  name = local.enhanced_monitoring_role_name

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "monitoring.rds.amazonaws.com"
      }
    }]
  })

  tags = {
    Name        = local.enhanced_monitoring_role_name
    Environment = var.environment
  }
}

data "aws_iam_role" "enhanced_monitoring" {
  count = var.enhanced_monitoring_interval > 0 && var.role == "secondary" ? 1 : 0

  name = local.enhanced_monitoring_role_name
}

resource "aws_iam_role_policy_attachment" "enhanced_monitoring" {
  count = var.enhanced_monitoring_interval > 0 && var.role == "primary" ? 1 : 0

  role       = aws_iam_role.enhanced_monitoring[0].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonRDSEnhancedMonitoringRole"
}

locals {
  enhanced_monitoring_role_arn = var.enhanced_monitoring_interval > 0 ? (
    var.role == "primary" ? aws_iam_role.enhanced_monitoring[0].arn : data.aws_iam_role.enhanced_monitoring[0].arn
  ) : null
}

resource "aws_rds_cluster_instance" "this" {
  count = var.instance_count

  identifier         = "${local.name}-${count.index + 1}"
  cluster_identifier = aws_rds_cluster.this.id
  instance_class     = var.instance_class
  engine             = aws_rds_cluster.this.engine
  engine_version     = aws_rds_cluster.this.engine_version

  publicly_accessible             = false
  auto_minor_version_upgrade      = true
  performance_insights_enabled    = var.kms_key_arn != ""
  performance_insights_kms_key_id = var.kms_key_arn != "" ? var.kms_key_arn : null
  monitoring_interval             = var.enhanced_monitoring_interval
  monitoring_role_arn             = local.enhanced_monitoring_role_arn

  tags = {
    Name        = "${local.name}-${count.index + 1}"
    Environment = var.environment
  }
}
