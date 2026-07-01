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
