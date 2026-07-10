variable "project" {
  type    = string
  default = "contenthub"
}

variable "environment" {
  description = "Same as primary prod (us-east-1); DR is a second region, not a separate env."
  type        = string
  default     = "prod"
}

variable "deploy_mode" {
  type    = string
  default = "cht-vpc"
}

# ── Primary prod fields (shared tfvars) ─────────────────────────────────────

variable "api_domain" {
  type = string
}

variable "acm_certificate_arn" {
  type    = string
  default = ""
}

variable "api_image" {
  type = string
}

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

variable "enable_aurora_global" {
  type    = bool
  default = true
}

variable "aurora_instance_class" {
  type    = string
  default = "db.r6g.large"
}

variable "aurora_engine_version" {
  type    = string
  default = "15.17"
}

variable "aurora_use_for_app" {
  type    = bool
  default = true
}

variable "rds_backup_retention" {
  type    = number
  default = 30
}

variable "log_retention_days" {
  type    = number
  default = 365
}

# ── DR (us-east-2) — consumed by this stack only ────────────────────────────

variable "dr_vpc_id" {
  type = string
}

variable "dr_private_subnet_ids" {
  type = list(string)
}

variable "dr_public_subnet_ids" {
  type = list(string)
}

variable "dr_acm_certificate_arn" {
  type    = string
  default = ""
}

variable "dr_cht_backend_security_group_id" {
  type = string
}

variable "dr_cht_nat_gateway_cidr_blocks" {
  type = list(string)
}

variable "dr_alb_allow_public_ingress" {
  type    = bool
  default = false
}

variable "dr_enable_waf" {
  type    = bool
  default = false
}

variable "dr_manage_route53" {
  type    = bool
  default = false
}

variable "dr_standby_scale_factor" {
  type    = number
  default = 0.5
}

variable "dr_deploy_api_ecs_service" {
  type    = bool
  default = false
}

variable "dr_api_image" {
  description = "us-east-2 ECR image; defaults to api_image with us-east-2 registry when empty."
  type        = string
  default     = ""
}

variable "enable_route53_failover" {
  type        = bool
  default     = false
  description = "Opens Route53 health-checker ingress on DR ALB; pair with enable_route53_failover on us-east-1."
}

variable "primary_state_bucket" {
  type    = string
  default = "cht-contenthub-terraform-state"
}

variable "primary_state_key" {
  type    = string
  default = "contenthub/terraform.tfstate"
}
