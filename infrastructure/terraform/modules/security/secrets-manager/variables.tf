variable "project" {
  type = string
}

variable "environment" {
  type = string
}

variable "kms_key_id" {
  description = "Optional KMS key ID/ARN for secrets encryption (omit for AWS-managed key)."
  type        = string
  default     = ""
}

variable "replica_regions" {
  description = "Secrets Manager multi-region replicas (e.g. us-east-2 DR)."
  type = list(object({
    region     = string
    kms_key_id = optional(string)
  }))
  default = []
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

# Platform integration + AI keys (stored in app-secrets JSON; injected into ECS when set).

variable "openai_api_key" {
  type      = string
  sensitive = true
  default   = ""
}

variable "anthropic_api_key" {
  type      = string
  sensitive = true
  default   = ""
}

variable "linkedin_client_id" {
  type      = string
  sensitive = true
  default   = ""
}

variable "linkedin_client_secret" {
  type      = string
  sensitive = true
  default   = ""
}

variable "linkedin_redirect_uri" {
  type    = string
  default = ""
}

variable "linkedin_scopes" {
  type    = string
  default = ""
}

variable "linkedin_org_urn" {
  type    = string
  default = ""
}

variable "linkedin_ad_account_id" {
  type    = string
  default = ""
}

variable "linkedin_ads_access_token" {
  type      = string
  sensitive = true
  default   = ""
}

variable "linkedin_ads_client_id" {
  type      = string
  sensitive = true
  default   = ""
}

variable "linkedin_ads_client_secret" {
  type      = string
  sensitive = true
  default   = ""
}

variable "linkedin_ads_redirect_uri" {
  type    = string
  default = ""
}

variable "linkedin_ads_scopes" {
  type    = string
  default = ""
}

variable "youtube_api_key" {
  type      = string
  sensitive = true
  default   = ""
}

variable "youtube_channel_id" {
  type    = string
  default = ""
}

variable "youtube_channel_handle" {
  type    = string
  default = ""
}

variable "x_bearer_token" {
  type      = string
  sensitive = true
  default   = ""
}

variable "x_account_handle" {
  type    = string
  default = ""
}

variable "wordpress_webhook_secret" {
  type      = string
  sensitive = true
  default   = ""
}
