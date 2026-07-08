variable "project" {
  type = string
}

variable "environment" {
  type = string
}

variable "public_api_key" {
  type      = string
  sensitive = true
}

variable "webhook_api_key" {
  type      = string
  sensitive = true
}

variable "jwt_secret" {
  type      = string
  sensitive = true
}

variable "internal_cache_secret" {
  type      = string
  sensitive = true
  default   = ""
}
