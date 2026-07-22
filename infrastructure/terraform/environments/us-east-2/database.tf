module "aurora_global" {
  count  = local.aurora_global_enabled ? 1 : 0
  source = "../../modules/database/aurora-global"

  role                      = "secondary"
  project                   = var.project
  environment               = var.environment
  vpc_id                    = local.vpc_id
  private_subnet_ids        = local.private_subnet_ids
  allowed_security_groups   = []
  kms_key_arn               = module.kms.rds_kms_key_arn
  instance_class            = var.aurora_instance_class
  engine_version            = local.primary_aurora_engine_version
  global_cluster_identifier = local.primary_aurora_global_cluster_id
  backup_retention_period   = var.rds_backup_retention
  instance_count            = 1
  deletion_protection       = true
}

locals {
  primary_db_secret = jsondecode(data.aws_secretsmanager_secret_version.primary_database.secret_string)

  database_secret_arn = aws_secretsmanager_secret.database.arn
  dr_database_host    = local.aurora_global_enabled ? module.aurora_global[0].reader_host : local.primary_db_secret.host
}

resource "aws_secretsmanager_secret" "database" {
  name                    = "${local.resource_prefix}-database-credentials"
  description             = "DR database credentials (use2 reader host); credentials replicate from use1 Aurora secret."
  recovery_window_in_days = 30
}

resource "aws_secretsmanager_secret_version" "database" {
  secret_id = aws_secretsmanager_secret.database.id
  secret_string = jsonencode({
    username = local.primary_db_secret.username
    password = local.primary_db_secret.password
    host     = local.dr_database_host
    port     = local.primary_db_secret.port
    dbname   = local.primary_db_secret.dbname
    # The app uses SQLAlchemy `create_async_engine`, which requires an
    # async-explicit driver scheme. Bare `postgresql://` dispatches to the
    # default sync driver (psycopg2) and Alembic bails on startup with
    # "The asyncio extension requires an async driver to be used"
    # (verified 2026-07-21, DR task-def :9 crashloop). Primary secret in
    # modules/database/rds/main.tf:86 already uses this scheme.
    url = format(
      "postgresql+asyncpg://%s:%s@%s:%s/%s",
      local.primary_db_secret.username,
      urlencode(local.primary_db_secret.password),
      local.dr_database_host,
      local.primary_db_secret.port,
      local.primary_db_secret.dbname
    )
  })
}

resource "aws_vpc_security_group_ingress_rule" "rds_from_api" {
  count = local.aurora_global_enabled ? 1 : 0

  description                  = "PostgreSQL from DR contenthub-api ECS tasks"
  security_group_id            = module.aurora_global[0].security_group_id
  referenced_security_group_id = module.ecs_api.security_group_id
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
}
