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
  description = "Optional — not used by public ALB; document for network reviews"
  default     = ""
}

# Images
variable "api_image" {
  type = string
}

variable "worker_image" {
  type = string
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

variable "cht_cache_clear_url" {
  type    = string
  default = ""
}
