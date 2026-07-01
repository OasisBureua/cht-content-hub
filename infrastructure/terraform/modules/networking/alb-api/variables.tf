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
  description = "Public subnets for internet-facing ALB"
}

variable "certificate_arn" {
  type        = string
  description = "ACM certificate ARN for HTTPS listener (us-east-1)"
  default     = ""
}

variable "api_port" {
  type    = number
  default = 8000
}

variable "api_domain" {
  type        = string
  description = "Public hostname for CHT CONTENTHUB_BASE_URL (without path)"
  default     = ""
}
