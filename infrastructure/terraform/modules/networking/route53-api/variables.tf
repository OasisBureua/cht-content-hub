variable "project" {
  type = string
}

variable "environment" {
  type = string
}

variable "api_domain" {
  type        = string
  description = "Producer API FQDN — also the Route53 hosted zone name (e.g. devhub.communityhealth.media)"
}

variable "alb_dns_name" {
  type = string
}

variable "alb_zone_id" {
  type        = string
  description = "Route53 hosted zone ID of the ALB (for alias target)"
}

variable "enable_failover" {
  type        = bool
  default     = false
  description = "PRIMARY/SECONDARY failover records with health check on primary ALB."
}

variable "primary_region" {
  type        = string
  default     = "us-east-1"
  description = "Label for primary failover record set_identifier."
}

variable "secondary_region" {
  type        = string
  default     = "us-east-2"
  description = "Label for secondary failover record set_identifier."
}

variable "secondary_alb_dns_name" {
  type        = string
  default     = ""
  description = "DR ALB DNS name (required when enable_failover = true)."
}

variable "secondary_alb_zone_id" {
  type        = string
  default     = ""
  description = "DR ALB hosted zone ID (required when enable_failover = true)."
}

variable "failover_alarm_actions" {
  type        = list(string)
  default     = []
  description = "Optional SNS topic ARNs when primary health check fails."
}
