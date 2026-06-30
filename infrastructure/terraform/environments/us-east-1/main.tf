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
    bucket       = "mediahub-terraform-state"
    key          = "us-east-1/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
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
  log_retention   = contains(["prod", "platform"], var.environment) ? 365 : 7
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

module "app_secrets" {
  source = "../../modules/security/secrets-manager"

  project               = var.project
  environment           = var.environment
  public_api_key        = var.public_api_key
  webhook_api_key       = var.webhook_api_key
  jwt_secret            = var.jwt_secret
  internal_cache_secret = var.internal_cache_secret
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
  database_secret_arn   = module.rds.database_secret_arn
  app_secrets_arn       = module.app_secrets.app_secrets_arn
  task_cpu              = var.api_task_cpu
  task_memory           = var.api_task_memory
  desired_count         = var.api_desired_count
  min_capacity          = var.api_min_capacity
  max_capacity          = var.api_max_capacity
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

# Wire ECS → RDS after service security groups exist
resource "aws_vpc_security_group_ingress_rule" "rds_from_api" {
  security_group_id            = module.rds.security_group_id
  referenced_security_group_id = module.ecs_api.security_group_id
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
}

resource "aws_vpc_security_group_ingress_rule" "rds_from_worker" {
  count = var.worker_desired_count > 0 ? 1 : 0

  security_group_id            = module.rds.security_group_id
  referenced_security_group_id = module.ecs_worker[0].security_group_id
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
}


