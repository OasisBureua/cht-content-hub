variable "user_pool_id" {
  type        = string
  description = "Shared CHT Cognito user pool that already hosts the platform resource server."
}

variable "identifier" {
  type        = string
  default     = "hub"
  description = "Resource-server identifier. Tokens carry {identifier}/{scope_name}."
}

variable "name" {
  type        = string
  default     = "Content Hub API"
  description = "Console display name for the Hub resource server."
}

variable "scopes" {
  type = list(object({
    name        = string
    description = string
  }))
  description = "Custom scopes on this resource server (no identifier prefix)."
}

variable "create_m2m_client" {
  type        = bool
  default     = true
  description = "Create Hub's outbound client_credentials app client."
}

variable "m2m_client_name" {
  type        = string
  description = "App client name, e.g. cht-hub-m2m-dev."
}

variable "m2m_outbound_scopes" {
  type        = list(string)
  default     = ["platform/export.read"]
  description = "Full scopes Hub may request when calling other services (other RS identifiers)."
}

variable "m2m_secret_name" {
  type        = string
  default     = ""
  description = "Secrets Manager name for Hub M2M JSON. Empty skips the secret."
}

variable "token_url" {
  type        = string
  default     = ""
  description = "Cognito token endpoint stored in the M2M secret."
}

variable "environment" {
  type = string
}
