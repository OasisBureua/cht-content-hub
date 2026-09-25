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

variable "source_code_hash" {
  type        = string
  default     = ""
  description = "When set, used instead of hashing the zip. Pass a hash of repo sources so pip/zip timestamp churn does not update the function."
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

variable "extra_env" {
  type        = map(string)
  default     = {}
  description = "Additional environment variables merged into the Lambda's env. Job-specific; module-level defaults still win on key collision."
}

variable "extra_secret_arns" {
  type        = list(string)
  default     = []
  description = "Additional Secrets Manager ARNs the Lambda may GetSecretValue (e.g. Cognito M2M export)."
}

variable "enabled" {
  type    = bool
  default = true
}
