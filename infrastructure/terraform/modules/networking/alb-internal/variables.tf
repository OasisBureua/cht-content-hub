variable "project" {
  type = string
}

variable "environment" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "subnet_ids" {
  type        = list(string)
  description = "Private subnets for internal ALB"
}

variable "allowed_security_group_ids" {
  type        = list(string)
  description = "SGs allowed to reach the ALB (e.g. cht-backend)"
}

variable "api_port" {
  type    = number
  default = 8000
}
