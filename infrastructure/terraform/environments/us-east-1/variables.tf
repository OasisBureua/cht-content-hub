variable "project" {
  type        = string
  default     = "contenthub"
  description = "Resource name prefix (contenthub-dev-api, etc.)"
}

variable "environment" {
  type = string
}

variable "deploy_mode" {
  description = "cht-vpc (default): share CHT VPC/subnets; Terraform creates contenthub-{env}-cluster. standalone: own VPC (not wired yet)."
  type        = string
  default     = "cht-vpc"

  validation {
    condition     = contains(["cht-vpc", "standalone"], var.deploy_mode)
    error_message = "deploy_mode must be cht-vpc or standalone."
  }
}

# Networking — from CHT Terraform outputs when deploy_mode = cht-vpc
variable "vpc_id" {
  type = string
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "public_subnet_ids" {
  type        = list(string)
  description = "Public subnets for internet-facing API ALB"
}

variable "api_domain" {
  type        = string
  description = "Producer API hostname — dev: devhub.communityhealth.media, prod: contenthub.communityhealth.media"
}

variable "acm_certificate_arn" {
  type        = string
  description = "ACM cert in us-east-1 for API ALB HTTPS"
  default     = ""
}

# Deprecated — CHT uses public URL; kept optional for future tightening
variable "cht_backend_security_group_id" {
  type        = string
  description = "CHT backend ECS security group — ALB accepts HTTPS/HTTP from this SG (in-VPC path)"
  default     = ""
}

variable "cht_nat_gateway_cidr_blocks" {
  type        = list(string)
  description = "CHT NAT gateway public IPs (/32) — ALB accepts HTTPS when ECS egress hairpins via public devhub URL"
  default     = []
}

variable "alb_allow_public_ingress" {
  type        = bool
  description = "Allow 0.0.0.0/0 on ALB ports 80/443. Set false with cht_backend_security_group_id for CHT-only access."
  default     = true

  validation {
    condition     = var.alb_allow_public_ingress || var.cht_backend_security_group_id != "" || length(var.cht_nat_gateway_cidr_blocks) > 0
    error_message = "When alb_allow_public_ingress is false, set cht_backend_security_group_id and/or cht_nat_gateway_cidr_blocks."
  }
}

variable "enable_waf" {
  type        = bool
  description = "Attach regional WAF Web ACL to the API ALB (rate limit + managed rules)"
  default     = false

  validation {
    condition     = !var.enable_waf || var.acm_certificate_arn != ""
    error_message = "enable_waf requires acm_certificate_arn — WAF sits in front of the HTTPS listener."
  }
}

# Images
variable "api_image" {
  type = string
}

variable "worker_image" {
  type        = string
  default     = "233636046512.dkr.ecr.us-east-1.amazonaws.com/contenthub-api:unused"
  description = "Unused when worker_desired_count = 0 (ECS worker retired; Lambdas handle async work)."
}

# RDS
variable "rds_instance_class" {
  type    = string
  default = "db.t4g.micro"
}

variable "rds_engine_version" {
  type    = string
  default = "15.17"
}

variable "rds_allocated_storage" {
  type    = number
  default = 20
}

variable "rds_multi_az" {
  type    = bool
  default = false
}

variable "rds_backup_retention" {
  type    = number
  default = 7
}

variable "enable_aurora_global" {
  description = "Provision Aurora PostgreSQL Global Database (parallel to RDS until cutover)"
  type        = bool
  default     = false
}

variable "aurora_instance_class" {
  description = "Aurora instance class for Global Database primary"
  type        = string
  default     = "db.r6g.large"
}

variable "aurora_engine_version" {
  description = "Aurora PostgreSQL engine version"
  type        = string
  default     = "15.17"
}

variable "aurora_use_for_app" {
  description = "Point ECS/Lambdas at Aurora credentials (requires enable_aurora_global)"
  type        = bool
  default     = false
}

variable "decommission_rds" {
  description = "Remove standalone RDS after Aurora cutover (requires enable_aurora_global and aurora_use_for_app)"
  type        = bool
  default     = false

  validation {
    condition     = !var.decommission_rds || (var.enable_aurora_global && var.aurora_use_for_app)
    error_message = "decommission_rds requires enable_aurora_global = true and aurora_use_for_app = true."
  }
}

variable "log_retention_days" {
  type        = number
  default     = null
  description = "CloudWatch log retention for ECS and sync Lambdas. Defaults to 365 (prod/platform) or 7 (dev/staging)."
}

# Redis
variable "redis_node_type" {
  type    = string
  default = "cache.t3.micro"
}

# ECS sizing — api
variable "api_task_cpu" {
  type    = number
  default = 512
}

variable "api_task_memory" {
  type    = number
  default = 1024
}

variable "api_desired_count" {
  type    = number
  default = 1
}

variable "api_min_capacity" {
  type    = number
  default = 1
}

variable "api_max_capacity" {
  type    = number
  default = 2
}

variable "deploy_api_ecs_service" {
  type        = bool
  default     = true
  description = "When false, Terraform creates ECS task definition + SG but not the running service (deploy API locally)."
}

# ECS sizing — worker
variable "worker_task_cpu" {
  type    = number
  default = 512
}

variable "worker_task_memory" {
  type    = number
  default = 1024
}

variable "worker_desired_count" {
  type    = number
  default = 0
}

# Secrets (set via TF_VAR_* or tfvars — never commit real values)
variable "public_api_key" {
  type      = string
  sensitive = true
}

variable "webhook_api_key" {
  type      = string
  sensitive = true
}

variable "jwt_secret" {
  type      = string
  sensitive = true
}

variable "internal_cache_secret" {
  type      = string
  sensitive = true
  default   = ""
}

# Platform integration secrets — pass via dev.tfvars / prod.tfvars or TF_VAR_* (GitHub Actions).

variable "openai_api_key" {
  type      = string
  sensitive = true
  default   = ""
}

variable "anthropic_api_key" {
  type      = string
  sensitive = true
  default   = ""
}

variable "linkedin_client_id" {
  type      = string
  sensitive = true
  default   = ""
}

variable "linkedin_client_secret" {
  type      = string
  sensitive = true
  default   = ""
}

variable "linkedin_redirect_uri" {
  type    = string
  default = ""
}

variable "linkedin_scopes" {
  type    = string
  default = ""
}

variable "linkedin_org_urn" {
  type    = string
  default = ""
}

variable "linkedin_ad_account_id" {
  type    = string
  default = ""
}

variable "linkedin_ads_access_token" {
  type      = string
  sensitive = true
  default   = ""
}

variable "linkedin_ads_client_id" {
  type      = string
  sensitive = true
  default   = ""
}

variable "linkedin_ads_client_secret" {
  type      = string
  sensitive = true
  default   = ""
}

variable "linkedin_ads_redirect_uri" {
  type    = string
  default = ""
}

variable "linkedin_ads_scopes" {
  type    = string
  default = ""
}

variable "youtube_api_key" {
  type      = string
  sensitive = true
  default   = ""
}

variable "youtube_channel_id" {
  type    = string
  default = ""
}

variable "youtube_channel_handle" {
  type    = string
  default = ""
}

variable "x_bearer_token" {
  type      = string
  sensitive = true
  default   = ""
}

variable "x_account_handle" {
  type    = string
  default = ""
}

variable "wordpress_webhook_secret" {
  type      = string
  sensitive = true
  default   = ""
}

variable "manage_route53" {
  type        = bool
  default     = true
  description = "Create Route53 hosted zone + ALB alias for api_domain (R53 → ALB → ECS → RDS)"
}

variable "cht_cache_clear_url" {
  type    = string
  default = ""
}

variable "sync_lambda_package_path" {
  type        = string
  default     = ""
  description = "Path to dist/sync-lambda.zip — default: repo dist/sync-lambda.zip (run ./scripts/build-sync-lambda.sh before apply)"
}

variable "sync_jobs_enabled" {
  type        = map(bool)
  default     = {}
  description = "Override per-job enablement; unset jobs use defaults in sync_jobs.tf"
}
