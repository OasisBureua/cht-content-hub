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
  description = "SQS queue ARN — when non-empty, grants sqs:SendMessage on the ECS task role so /api/wordpress/webhook can enqueue events"
  type        = string
  default     = ""
}
