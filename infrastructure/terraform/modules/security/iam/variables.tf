variable "project" {
  type = string
}

variable "environment" {
  type = string
}

variable "aws_region" {
  type = string
}

variable "aws_account_id" {
  type = string
}

variable "wordpress_events_queue_arn" {
  description = "SQS queue ARN — when non-empty, grants sqs:SendMessage on the ECS task role so /api/wordpress/webhook can enqueue events. May be an apply-time value; use wordpress_ingest_enabled to gate resource creation."
  type        = string
  default     = ""
}

variable "wordpress_ingest_enabled" {
  description = "Static flag (plan-time known) for gating the WordPress SQS IAM policy count. Set true when the wordpress_ingest sync job is enabled."
  type        = bool
  default     = false
}

variable "hcp_intel_poll_queue_arn" {
  description = "SQS queue ARN — when non-empty, grants sqs:SendMessage on the ECS task role so POST /api/admin/kols/{slug}/refresh can enqueue single-NPI intel polls. May be an apply-time value; use hcp_intel_poll_enabled to gate resource creation."
  type        = string
  default     = ""
}

variable "hcp_intel_poll_enabled" {
  description = "Static flag (plan-time known) for gating the hcp_intel_poll SQS IAM policy count. Set true when the hcp_intel_poll sync job is enabled."
  type        = bool
  default     = false
}
