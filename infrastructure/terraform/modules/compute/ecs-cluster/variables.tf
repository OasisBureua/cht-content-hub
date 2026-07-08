variable "project" {
  type = string
}

variable "environment" {
  type = string
}

variable "enable_container_insights" {
  type    = bool
  default = true
}

variable "log_retention_days" {
  type    = number
  default = 7
}

variable "cloudwatch_kms_key_arn" {
  type    = string
  default = ""
}
