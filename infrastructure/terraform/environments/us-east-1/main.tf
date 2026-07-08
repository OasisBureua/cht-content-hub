terraform {
  required_version = ">= 1.10.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.0"
    }
  }

  backend "s3" {
    bucket       = "cht-contenthub-terraform-state"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
    # State key: pass via -backend-config=../backends/us-east-1-{dev|prod}.hcl
  }
}

provider "aws" {
  region = "us-east-1"

  default_tags {
    tags = {
      Project     = var.project
      Environment = var.environment
      Region      = "us-east-1"
      ManagedBy   = "Terraform"
    }
  }
}

data "aws_caller_identity" "current" {}

locals {
  resource_prefix = contains(["prod", "platform"], var.environment) ? var.project : "${var.project}-${var.environment}"
  log_retention   = coalesce(
    var.log_retention_days,
    contains(["prod", "platform"], var.environment) ? 365 : 7
  )
  api_image_tag   = try(element(split(":", var.api_image), 1), "unknown")
}

module "ecs_cluster" {
  source = "../../modules/compute/ecs-cluster"

  project            = var.project
  environment        = var.environment
  log_retention_days = local.log_retention
}

locals {
  cluster_id     = module.ecs_cluster.cluster_id
  cluster_name   = module.ecs_cluster.cluster_name
  log_group_name = module.ecs_cluster.log_group_name
}

module "iam" {
  source = "../../modules/security/iam"

  project         = var.project
  environment     = var.environment
  aws_region      = "us-east-1"
  aws_account_id  = data.aws_caller_identity.current.account_id
}

module "s3_assets" {
  source = "../../modules/storage/s3-assets"

  project        = var.project
  environment    = var.environment
  aws_account_id = data.aws_caller_identity.current.account_id
  task_role_arn  = module.iam.task_role_arn
}

module "app_secrets" {
  source = "../../modules/security/secrets-manager"

  project               = var.project
  environment           = var.environment
  public_api_key        = var.public_api_key
  webhook_api_key       = var.webhook_api_key
  jwt_secret            = var.jwt_secret
  internal_cache_secret = var.internal_cache_secret

  openai_api_key             = var.openai_api_key
  anthropic_api_key          = var.anthropic_api_key
  linkedin_client_id         = var.linkedin_client_id
  linkedin_client_secret     = var.linkedin_client_secret
  linkedin_redirect_uri      = var.linkedin_redirect_uri
  linkedin_scopes            = var.linkedin_scopes
  linkedin_org_urn           = var.linkedin_org_urn
  linkedin_ad_account_id     = var.linkedin_ad_account_id
  linkedin_ads_access_token  = var.linkedin_ads_access_token
  linkedin_ads_client_id     = var.linkedin_ads_client_id
  linkedin_ads_client_secret = var.linkedin_ads_client_secret
  linkedin_ads_redirect_uri  = var.linkedin_ads_redirect_uri
  linkedin_ads_scopes        = var.linkedin_ads_scopes
  youtube_api_key            = var.youtube_api_key
  youtube_channel_id         = var.youtube_channel_id
  youtube_channel_handle     = var.youtube_channel_handle
  x_bearer_token             = var.x_bearer_token
  x_account_handle           = var.x_account_handle
  wordpress_webhook_secret   = var.wordpress_webhook_secret
}

module "rds" {
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

module "alb_api" {
  source = "../../modules/networking/alb-api"

  project         = var.project
  environment     = var.environment
  vpc_id          = var.vpc_id
  subnet_ids      = var.public_subnet_ids
  certificate_arn = var.acm_certificate_arn
  api_domain      = var.api_domain

  allow_public_ingress = var.alb_allow_public_ingress
  allowed_ingress_security_group_ids = compact([
    var.cht_backend_security_group_id,
  ])
  allowed_ingress_cidr_blocks = var.cht_nat_gateway_cidr_blocks
}

module "waf_alb" {
  count  = var.enable_waf ? 1 : 0
  source = "../../modules/security/waf-alb"

  project     = var.project
  environment = var.environment
  alb_arn     = module.alb_api.alb_arn
}

module "route53_api" {
  count  = var.manage_route53 ? 1 : 0
  source = "../../modules/networking/route53-api"

  project     = var.project
  environment = var.environment
  api_domain  = var.api_domain

  alb_dns_name = module.alb_api.alb_dns_name
  alb_zone_id  = module.alb_api.alb_zone_id
}

module "ecs_api" {
  source = "../../modules/compute/ecs-api"

  project               = var.project
  environment           = var.environment
  aws_region            = "us-east-1"
  vpc_id                = var.vpc_id
  private_subnet_ids    = var.private_subnet_ids
  cluster_id            = local.cluster_id
  cluster_name          = local.cluster_name
  execution_role_arn    = module.iam.execution_role_arn
  task_role_arn         = module.iam.task_role_arn
  alb_security_group_id = module.alb_api.alb_security_group_id
  target_group_arn      = module.alb_api.target_group_arn
  alb_listener_arn      = module.alb_api.listener_arn
  log_group_name        = local.log_group_name
  container_image       = var.api_image
  app_version           = local.api_image_tag
  database_secret_arn   = module.rds.database_secret_arn
  app_secrets_arn       = module.app_secrets.app_secrets_arn
  task_cpu              = var.api_task_cpu
  task_memory           = var.api_task_memory
  desired_count         = var.api_desired_count
  min_capacity          = var.api_min_capacity
  max_capacity          = var.api_max_capacity

  depends_on = [module.rds, module.app_secrets]
}

module "ecs_worker" {
  count  = var.worker_desired_count > 0 ? 1 : 0
  source = "../../modules/compute/ecs-worker"

  project             = var.project
  environment         = var.environment
  aws_region          = "us-east-1"
  vpc_id              = var.vpc_id
  private_subnet_ids  = var.private_subnet_ids
  cluster_id          = local.cluster_id
  cluster_name        = local.cluster_name
  execution_role_arn  = module.iam.execution_role_arn
  task_role_arn       = module.iam.task_role_arn
  log_group_name      = local.log_group_name
  container_image     = var.worker_image
  database_secret_arn = module.rds.database_secret_arn
  app_secrets_arn     = module.app_secrets.app_secrets_arn
  cht_cache_clear_url = var.cht_cache_clear_url
  task_cpu            = var.worker_task_cpu
  task_memory         = var.worker_task_memory
  desired_count       = var.worker_desired_count
}

# ECS → RDS (separate rules avoid Terraform cycle: rds secrets ↔ ecs_api SG)
resource "aws_vpc_security_group_ingress_rule" "rds_from_api" {
  description                  = "PostgreSQL from contenthub-api ECS tasks"
  security_group_id            = module.rds.security_group_id
  referenced_security_group_id = module.ecs_api.security_group_id
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
}

resource "aws_vpc_security_group_ingress_rule" "rds_from_worker" {
  count = var.worker_desired_count > 0 ? 1 : 0

  description                  = "PostgreSQL from contenthub-worker ECS tasks"
  security_group_id            = module.rds.security_group_id
  referenced_security_group_id = module.ecs_worker[0].security_group_id
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
}
