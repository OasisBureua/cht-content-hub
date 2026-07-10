# Shared prod tfvars are used for deploy-contenthub-infra-local.sh and
# deploy-contenthub-secondary.sh. Declare primary-region-only keys here so
# Terraform does not warn about undeclared variables; this stack does not consume them.

variable "vpc_id" {
  description = "Primary only: us-east-1 VPC ID."
  type        = string
  default     = ""
}

variable "private_subnet_ids" {
  description = "Primary only: us-east-1 private subnets."
  type        = list(string)
  default     = []
}

variable "public_subnet_ids" {
  description = "Primary only: us-east-1 public subnets."
  type        = list(string)
  default     = []
}

variable "cht_backend_security_group_id" {
  description = "Primary only: CHT backend SG for us-east-1 ALB ingress."
  type        = string
  default     = ""
}

variable "cht_nat_gateway_cidr_blocks" {
  description = "Primary only: CHT NAT egress CIDRs for us-east-1 ALB ingress."
  type        = list(string)
  default     = []
}

variable "wordpress_ingress_cidr_blocks" {
  description = "Primary only: WordPress egress CIDRs for ALB webhook ingress."
  type        = list(string)
  default     = []
}

variable "alb_allow_public_ingress" {
  description = "Primary only: allow public ingress on us-east-1 ALB."
  type        = bool
  default     = false
}

variable "enable_waf" {
  description = "Primary only: enable WAF on us-east-1 ALB."
  type        = bool
  default     = false
}

variable "manage_route53" {
  description = "Primary only: manage Route53 zone for api_domain in us-east-1."
  type        = bool
  default     = true
}

variable "deploy_api_ecs_service" {
  description = "Primary only: create ECS API service in us-east-1."
  type        = bool
  default     = false
}

variable "decommission_rds" {
  description = "Primary only: remove standalone RDS after Aurora cutover."
  type        = bool
  default     = false
}

variable "rds_instance_class" {
  description = "Primary only: RDS instance class in us-east-1."
  type        = string
  default     = "db.t4g.small"
}

variable "rds_engine_version" {
  description = "Primary only: RDS/Aurora engine version in us-east-1."
  type        = string
  default     = "15.17"
}

variable "rds_allocated_storage" {
  description = "Primary only: RDS allocated storage (GB) in us-east-1."
  type        = number
  default     = 20
}

variable "rds_multi_az" {
  description = "Primary only: enable Multi-AZ on us-east-1 RDS."
  type        = bool
  default     = false
}

variable "redis_node_type" {
  description = "Primary only: ElastiCache node type (unused)."
  type        = string
  default     = ""
}

variable "worker_image" {
  description = "Primary only: retired worker image."
  type        = string
  default     = ""
}

variable "worker_task_cpu" {
  description = "Primary only: retired worker task CPU."
  type        = number
  default     = 512
}

variable "worker_task_memory" {
  description = "Primary only: retired worker task memory."
  type        = number
  default     = 1024
}

variable "worker_desired_count" {
  description = "Primary only: retired worker desired count."
  type        = number
  default     = 0
}

variable "enable_ecr_replication" {
  description = "Primary only: replicate ECR images to DR region."
  type        = bool
  default     = false
}

variable "ecr_replication_destination_region" {
  description = "Primary only: ECR replication destination region."
  type        = string
  default     = "us-east-2"
}

variable "secrets_kms_key_id" {
  description = "Primary only: KMS key for secrets encryption in us-east-1."
  type        = string
  default     = ""
}

variable "secrets_replica_kms_key_ids" {
  description = "Primary only: per-region KMS keys for SM replicas."
  type        = map(string)
  default     = {}
}

variable "cht_cache_clear_url" {
  description = "Primary only: CHT cache clear webhook URL."
  type        = string
  default     = ""
}

variable "sync_lambda_package_path" {
  description = "Primary only: path to sync Lambda deployment package."
  type        = string
  default     = ""
}

variable "sync_jobs_enabled" {
  description = "Primary only: EventBridge sync job toggles."
  type        = map(bool)
  default     = {}
}

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

variable "public_api_key" {
  description = "Primary only: stored in use1 SM; use2 copies from primary secret."
  type        = string
  sensitive   = true
  default     = ""
}

variable "webhook_api_key" {
  type      = string
  sensitive = true
  default   = ""
}

variable "jwt_secret" {
  type      = string
  sensitive = true
  default   = ""
}

variable "internal_cache_secret" {
  type      = string
  sensitive = true
  default   = ""
}

variable "secrets_replica_regions" {
  description = "Primary only: Secrets Manager replica regions."
  type        = list(string)
  default     = []
}

variable "route53_failover_alarm_actions" {
  description = "Primary only: SNS ARNs for Route53 primary health check alarm."
  type        = list(string)
  default     = []
}
