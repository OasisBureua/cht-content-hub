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
  }
}

provider "aws" {
  region = "us-east-2"

  default_tags {
    tags = {
      Project     = var.project
      Environment = var.environment
      Region      = "us-east-2"
      Purpose     = "DisasterRecovery"
      ManagedBy   = "Terraform"
    }
  }
}

provider "aws" {
  alias  = "use1"
  region = "us-east-1"
}

data "aws_caller_identity" "current" {}

data "terraform_remote_state" "primary" {
  backend = "s3"

  config = {
    bucket = var.primary_state_bucket
    key    = var.primary_state_key
    region = "us-east-1"
  }
}

data "aws_secretsmanager_secret" "primary_app" {
  provider = aws.use1
  name     = "contenthub-app-secrets"
}

data "aws_secretsmanager_secret_version" "primary_app" {
  provider  = aws.use1
  secret_id = data.aws_secretsmanager_secret.primary_app.id
}

data "aws_secretsmanager_secret" "primary_database" {
  provider = aws.use1
  name     = "contenthub-aurora-database-credentials"
}

data "aws_secretsmanager_secret_version" "primary_database" {
  provider  = aws.use1
  secret_id = data.aws_secretsmanager_secret.primary_database.id
}

module "ecs_cluster" {
  source = "../../modules/compute/ecs-cluster"

  project            = local.dr_project
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

  project        = local.dr_project
  environment    = var.environment
  aws_region     = "us-east-2"
  aws_account_id = data.aws_caller_identity.current.account_id
}

resource "aws_secretsmanager_secret" "app_secrets" {
  name                    = "${local.resource_prefix}-app-secrets"
  description             = "DR regional app secrets (us-east-2); seeded from use1 primary. SM replicas also exist for sync."
  recovery_window_in_days = 30
}

resource "aws_secretsmanager_secret_version" "app_secrets" {
  secret_id     = aws_secretsmanager_secret.app_secrets.id
  secret_string = data.aws_secretsmanager_secret_version.primary_app.secret_string
}

module "alb_api" {
  source = "../../modules/networking/alb-api"

  project         = local.dr_project
  environment     = var.environment
  vpc_id          = local.vpc_id
  subnet_ids      = local.public_subnet_ids
  certificate_arn = local.acm_certificate_arn
  api_domain      = var.api_domain

  allow_public_ingress = var.dr_alb_allow_public_ingress
  allowed_ingress_security_group_ids = compact([
    var.dr_cht_backend_security_group_id,
  ])
  allowed_ingress_cidr_blocks = var.dr_cht_nat_gateway_cidr_blocks

  allow_route53_health_check_ingress = var.enable_route53_failover
}

module "ecs_api" {
  source = "../../modules/compute/ecs-api"

  project               = local.dr_project
  environment           = var.environment
  aws_region            = "us-east-2"
  vpc_id                = local.vpc_id
  private_subnet_ids    = local.private_subnet_ids
  cluster_id            = local.cluster_id
  cluster_name          = local.cluster_name
  execution_role_arn    = module.iam.execution_role_arn
  task_role_arn         = module.iam.task_role_arn
  alb_security_group_id = module.alb_api.alb_security_group_id
  target_group_arn      = module.alb_api.target_group_arn
  alb_listener_arn      = module.alb_api.listener_arn
  log_group_name        = local.log_group_name
  container_image       = local.api_image
  app_version           = local.api_image_tag
  database_secret_arn   = local.database_secret_arn
  app_secrets_arn       = aws_secretsmanager_secret.app_secrets.arn
  task_cpu              = var.api_task_cpu
  task_memory           = var.api_task_memory
  desired_count         = local.api_desired_dr
  min_capacity          = local.api_min_dr
  max_capacity          = local.api_max_dr
  create_service        = var.dr_deploy_api_ecs_service
}
