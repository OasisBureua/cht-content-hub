# Sync Lambda jobs — same module + artifact per environment (separate function instances).

locals {
  sync_lambda_package = var.sync_lambda_package_path != "" ? var.sync_lambda_package_path : abspath("${path.module}/../../../../dist/sync-lambda.zip")

  sync_jobs = {
    cache_clear = {
      enabled                        = lookup(var.sync_jobs_enabled, "cache_clear", true)
      handler                        = "jobs.cache_clear.handler.handler"
      timeout                        = 60
      memory_size                    = 256
      schedule_expression            = null
      sqs_trigger                    = false
      reserved_concurrent_executions = -1
    }
    hcp_intel_poll = {
      enabled                        = lookup(var.sync_jobs_enabled, "hcp_intel_poll", true)
      handler                        = "jobs.hcp_intel_poll.handler.handler"
      timeout                        = 900
      memory_size                    = 1024
      schedule_expression            = "rate(30 minutes)"
      sqs_trigger                    = true
      reserved_concurrent_executions = 1
    }
    openalex_backfill = {
      enabled                        = lookup(var.sync_jobs_enabled, "openalex_backfill", true)
      handler                        = "jobs.openalex_backfill.handler.handler"
      timeout                        = 900
      memory_size                    = 1024
      schedule_expression            = "cron(30 3 ? * SUN *)"
      sqs_trigger                    = false
      reserved_concurrent_executions = 1
    }
    kol_hcp_matcher = {
      enabled                        = lookup(var.sync_jobs_enabled, "kol_hcp_matcher", true)
      handler                        = "jobs.kol_hcp_matcher.handler.handler"
      timeout                        = 300
      memory_size                    = 512
      schedule_expression            = "cron(0 4 * * ? *)"
      sqs_trigger                    = false
      reserved_concurrent_executions = 1
    }
    post_tagging = {
      enabled                        = lookup(var.sync_jobs_enabled, "post_tagging", false)
      handler                        = "jobs.post_tagging.handler.handler"
      timeout                        = 900
      memory_size                    = 1024
      schedule_expression            = "rate(12 hours)"
      sqs_trigger                    = false
      reserved_concurrent_executions = 1
    }
    playlist_doctor_tagger = {
      enabled                        = lookup(var.sync_jobs_enabled, "playlist_doctor_tagger", false)
      handler                        = "jobs.playlist_doctor_tagger.handler.handler"
      timeout                        = 900
      memory_size                    = 1024
      schedule_expression            = "cron(30 4 * * ? *)"
      sqs_trigger                    = false
      reserved_concurrent_executions = 1
    }
  }
}

module "sync_lambda" {
  for_each = { for name, cfg in local.sync_jobs : name => cfg if cfg.enabled }

  source = "../../modules/compute/lambda-job"

  project                 = var.project
  environment             = var.environment
  aws_region              = "us-east-1"
  job_name                = each.key
  handler                 = each.value.handler
  deployment_package_path = local.sync_lambda_package
  timeout                 = each.value.timeout
  memory_size             = each.value.memory_size
  schedule_expression     = each.value.schedule_expression
  sqs_trigger             = each.value.sqs_trigger
  reserved_concurrent_executions = each.value.reserved_concurrent_executions
  vpc_id                  = var.vpc_id
  private_subnet_ids      = var.private_subnet_ids
  database_secret_arn     = module.rds.database_secret_arn
  app_secrets_arn         = module.app_secrets.app_secrets_arn
  cht_cache_clear_url     = var.cht_cache_clear_url
  log_retention_days      = local.log_retention
  enabled                 = true

  depends_on = [module.rds, module.app_secrets]
}

resource "aws_vpc_security_group_ingress_rule" "rds_from_sync_lambda" {
  for_each = module.sync_lambda

  description                  = "PostgreSQL from sync Lambda ${each.key}"
  security_group_id            = module.rds.security_group_id
  referenced_security_group_id = each.value.security_group_id
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
}
