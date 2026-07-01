variable "project" {
  type = string
}

variable "environment" {
  type = string
}

variable "aws_region" {
  type = string
}

variable "job_name" {
  type        = string
  description = "Short job id, e.g. hcp_intel_poll"
}

variable "handler" {
  type        = string
  description = "Lambda handler path, e.g. jobs.hcp_intel_poll.handler.handler"
}

variable "deployment_package_path" {
  type        = string
  description = "Path to shared sync-lambda.zip"
}

variable "timeout" {
  type    = number
  default = 300
}

variable "memory_size" {
  type    = number
  default = 512
}

variable "reserved_concurrent_executions" {
  type        = number
  default     = -1
  description = "Set to 1 for serial jobs; -1 disables reserved concurrency"
}

variable "schedule_expression" {
  type        = string
  default     = null
  description = "EventBridge schedule, e.g. rate(30 minutes) or cron(30 3 ? * SUN *)"
}

variable "sqs_trigger" {
  type        = bool
  default     = false
  description = "When true with schedule, EventBridge publishes to SQS and Lambda consumes the queue"
}

variable "vpc_id" {
  type = string
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "database_secret_arn" {
  type = string
}

variable "app_secrets_arn" {
  type = string
}

variable "cht_cache_clear_url" {
  type    = string
  default = ""
}

variable "log_retention_days" {
  type    = number
  default = 7
}

variable "enabled" {
  type    = bool
  default = true
}
