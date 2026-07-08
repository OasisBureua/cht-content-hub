variable "project" {
  type = string
}

variable "environment" {
  type = string
}

variable "alb_arn" {
  description = "Application Load Balancer ARN to associate with the regional Web ACL"
  type        = string
}

variable "enable_managed_rules" {
  description = "Enable AWS managed rule sets (KnownBadInputs, IP reputation)"
  type        = bool
  default     = true
}

variable "enable_common_rule_set" {
  description = "Enable AWSManagedRulesCommonRuleSet (can false-positive on large JSON API bodies — off by default for Hub API)"
  type        = bool
  default     = false
}

variable "enable_rate_limit" {
  description = "Enable rate-based rule (limit requests per 5 min per IP)"
  type        = bool
  default     = true
}

variable "rate_limit_count" {
  description = "Max requests per 5 minutes per IP when rate limit enabled"
  type        = number
  default     = 5000
}
