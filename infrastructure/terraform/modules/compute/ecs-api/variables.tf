variable "project" {
  type = string
}

variable "environment" {
  type = string
}

variable "aws_region" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "cluster_id" {
  type = string
}

variable "cluster_name" {
  type = string
}

variable "execution_role_arn" {
  type = string
}

variable "task_role_arn" {
  type = string
}

variable "alb_security_group_id" {
  type = string
}

variable "target_group_arn" {
  type = string
}

variable "alb_listener_arn" {
  type = string
}

variable "log_group_name" {
  type = string
}

variable "container_image" {
  type = string
}

variable "database_secret_arn" {
  type = string
}

variable "app_secrets_arn" {
  type = string
}

variable "app_version" {
  type        = string
  default     = "unknown"
  description = "Container image tag for actuator/info"
}

variable "redis_url" {
  type    = string
  default = ""
}

variable "wordpress_events_queue_url" {
  type        = string
  description = "SQS queue URL — passed to contenthub-api as WORDPRESS_EVENTS_QUEUE_URL for /api/wordpress/webhook to enqueue events"
  default     = ""
}

variable "wordpress_events_queue_arn" {
  type        = string
  description = "SQS queue ARN — used to scope the sqs:SendMessage IAM permission on the ECS task role"
  default     = ""
}

variable "task_cpu" {
  type    = number
  default = 512
}

variable "task_memory" {
  type    = number
  default = 1024
}

variable "desired_count" {
  type    = number
  default = 1
}

variable "min_capacity" {
  type    = number
  default = 1
}

variable "max_capacity" {
  type    = number
  default = 2
}

variable "create_service" {
  type        = bool
  default     = true
  description = "When false, create task definition + SG only (no ECS service or autoscaling)."
}
