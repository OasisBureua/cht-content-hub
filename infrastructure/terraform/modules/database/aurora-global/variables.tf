variable "project" {
  description = "Project name"
  type        = string
}

variable "environment" {
  description = "Environment name"
  type        = string
}

variable "role" {
  description = "primary (us-east-1 writer) or secondary (us-east-2 reader cluster)"
  type        = string

  validation {
    condition     = contains(["primary", "secondary"], var.role)
    error_message = "role must be primary or secondary"
  }
}

variable "vpc_id" {
  description = "VPC ID"
  type        = string
}

variable "private_subnet_ids" {
  description = "Private subnet IDs for the DB subnet group"
  type        = list(string)
}

variable "allowed_security_groups" {
  description = "Security groups allowed to connect on port 5432"
  type        = list(string)
}

variable "kms_key_arn" {
  description = "Optional KMS key ARN for storage encryption (default AWS RDS key when empty)"
  type        = string
  default     = ""
}

variable "instance_class" {
  description = "Aurora instance class (e.g. db.r6g.large)"
  type        = string
  default     = "db.r6g.large"
}

variable "engine_version" {
  description = "Aurora PostgreSQL engine version"
  type        = string
  default     = "15.17"
}

variable "database_name" {
  description = "Initial database name (primary only)"
  type        = string
  default     = "contenthub_producer"
}

variable "master_username" {
  description = "Master username (primary only)"
  type        = string
  default     = "contenthub_admin"
}

variable "backup_retention_period" {
  description = "Backup retention in days"
  type        = number
  default     = 7
}

variable "global_cluster_identifier" {
  description = "Global cluster ID (required for secondary role)"
  type        = string
  default     = ""
}

variable "deletion_protection" {
  description = "Enable deletion protection on clusters"
  type        = bool
  default     = true
}

variable "instance_count" {
  description = "Number of Aurora instances per regional cluster (minimum 2 recommended for HA)"
  type        = number
  default     = 2

  validation {
    condition     = var.instance_count >= 1 && var.instance_count <= 15
    error_message = "instance_count must be between 1 and 15"
  }
}

variable "enhanced_monitoring_interval" {
  description = "Enhanced Monitoring interval in seconds (0 disables; valid: 1, 5, 10, 15, 30, 60)"
  type        = number
  default     = 60

  validation {
    condition     = contains([0, 1, 5, 10, 15, 30, 60], var.enhanced_monitoring_interval)
    error_message = "enhanced_monitoring_interval must be 0, 1, 5, 10, 15, 30, or 60"
  }
}

variable "enhanced_monitoring_role_name" {
  description = "Override IAM role name for RDS Enhanced Monitoring (secondary clusters default to {project}-aurora-enhanced-monitoring)"
  type        = string
  default     = ""
}

variable "iam_database_authentication_enabled" {
  description = "Enable IAM database authentication (password auth continues to work)"
  type        = bool
  default     = true
}
