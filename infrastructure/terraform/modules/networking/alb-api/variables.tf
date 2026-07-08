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

variable "allow_public_ingress" {
  type        = bool
  description = "Allow 0.0.0.0/0 on ports 80/443. Set false when restricting to allowed_ingress_security_group_ids."
  default     = true
}

variable "allowed_ingress_security_group_ids" {
  type        = list(string)
  description = "Security group IDs allowed to reach the ALB (e.g. CHT backend ECS SG). Used with allow_public_ingress = false."
  default     = []
}

variable "allowed_ingress_cidr_blocks" {
  type        = list(string)
  description = "CIDR blocks allowed HTTPS to the ALB (e.g. CHT NAT gateway /32s when ECS egress uses public devhub URL)."
  default     = []

  validation {
    condition = alltrue([
      for cidr in var.allowed_ingress_cidr_blocks :
      can(cidrhost(cidr, 0))
    ])
    error_message = "Each allowed_ingress_cidr_blocks entry must be a valid IPv4 CIDR (e.g. 10.0.0.1/32)."
  }
}

variable "ingress_cidr_description" {
  type        = string
  description = "Description for HTTPS rules sourced from allowed_ingress_cidr_blocks."
  default     = "CHT NAT (ECS egress via public devhub URL)"
}
