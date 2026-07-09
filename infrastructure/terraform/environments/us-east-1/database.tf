moved {
  from = module.rds
  to   = module.rds[0]
}

module "rds" {
  count  = var.enable_aurora_global && var.decommission_rds ? 0 : 1
  source = "../../modules/database/rds"

  project                 = var.project
  environment             = var.environment
  vpc_id                  = var.vpc_id
  private_subnet_ids      = var.private_subnet_ids
  allowed_security_groups = []
  engine_version          = var.rds_engine_version
  instance_class          = var.rds_instance_class
  allocated_storage       = var.rds_allocated_storage
  multi_az                = var.rds_multi_az
  backup_retention_period = var.rds_backup_retention
}

module "aurora_global" {
  count  = var.enable_aurora_global ? 1 : 0
  source = "../../modules/database/aurora-global"

  role                    = "primary"
  project                 = var.project
  environment             = var.environment
  vpc_id                  = var.vpc_id
  private_subnet_ids      = var.private_subnet_ids
  allowed_security_groups = []
  instance_class          = var.aurora_instance_class
  engine_version          = var.aurora_engine_version
  backup_retention_period = var.rds_backup_retention
  deletion_protection     = contains(["prod", "platform"], var.environment)
}

locals {
  aurora_app_active = var.enable_aurora_global && (var.aurora_use_for_app || var.decommission_rds)

  database_security_group_id = local.aurora_app_active ? module.aurora_global[0].security_group_id : module.rds[0].security_group_id
  database_secret_arn        = local.aurora_app_active ? aws_secretsmanager_secret.aurora_app[0].arn : module.rds[0].database_secret_arn
  database_secret_version_id = local.aurora_app_active ? aws_secretsmanager_secret_version.aurora_app[0].id : module.rds[0].database_secret_version_id
}

resource "aws_secretsmanager_secret" "aurora_app" {
  count = local.aurora_app_active ? 1 : 0

  name                    = "${local.resource_prefix}-aurora-database-credentials"
  description             = "Aurora Global writer credentials for Content Hub ${var.environment}"
  recovery_window_in_days = contains(["prod", "platform"], var.environment) ? 30 : 7

  tags = {
    Name        = "${local.resource_prefix}-aurora-database-credentials"
    Environment = var.environment
    Purpose     = "AuroraApp"
  }
}

resource "aws_secretsmanager_secret_version" "aurora_app" {
  count = local.aurora_app_active ? 1 : 0

  secret_id = aws_secretsmanager_secret.aurora_app[0].id
  secret_string = jsonencode({
    username = module.aurora_global[0].master_username
    password = module.aurora_global[0].master_password
    host     = module.aurora_global[0].cluster_endpoint
    port     = module.aurora_global[0].cluster_port
    dbname   = module.aurora_global[0].database_name
    url      = module.aurora_global[0].asyncpg_connection_string
  })
}

resource "aws_secretsmanager_secret" "aurora_migration" {
  count = var.enable_aurora_global && !local.aurora_app_active ? 1 : 0

  name                    = "${local.resource_prefix}-aurora-migration-credentials"
  description             = "Aurora Global writer credentials for RDS → Aurora migration (not used by ECS until cutover)"
  recovery_window_in_days = 7

  tags = {
    Name        = "${local.resource_prefix}-aurora-migration-credentials"
    Environment = var.environment
    Purpose     = "AuroraMigration"
  }
}

resource "aws_secretsmanager_secret_version" "aurora_migration" {
  count = var.enable_aurora_global && !local.aurora_app_active ? 1 : 0

  secret_id = aws_secretsmanager_secret.aurora_migration[0].id
  secret_string = jsonencode({
    username = module.aurora_global[0].master_username
    password = module.aurora_global[0].master_password
    host     = module.aurora_global[0].cluster_endpoint
    port     = module.aurora_global[0].cluster_port
    dbname   = module.aurora_global[0].database_name
    url      = module.aurora_global[0].asyncpg_connection_string
  })
}
