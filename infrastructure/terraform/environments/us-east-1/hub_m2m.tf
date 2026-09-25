# Hub's Cognito resource server on the shared CHT pool.
# Does not create an outbound client (create_m2m_client = false).
# No-op until cognito_user_pool_id is set.

locals {
  hub_m2m_scopes = [
    { name = "catalog.read", description = "Read Hub catalog (/api/public)" },
    { name = "catalog.create", description = "Create Hub catalog resources" },
    { name = "catalog.update", description = "Update Hub catalog resources" },
    { name = "catalog.delete", description = "Delete Hub catalog resources" },
    { name = "admin.read", description = "Read Hub admin (/api/admin)" },
    { name = "admin.create", description = "Create Hub admin resources" },
    { name = "admin.update", description = "Update Hub admin resources" },
    { name = "admin.delete", description = "Delete Hub admin resources" },
    { name = "reports.read", description = "Read campaign report-packet" },
  ]

  # Live access tokens on cht-dev-users use issuer-cognito-idp (not cognito-idp).
  # Hub decode also aliases the other host so either form verifies.
  hub_m2m_issuer = var.hub_m2m_issuer != "" ? var.hub_m2m_issuer : (
    var.cognito_user_pool_id != ""
    ? "https://issuer-cognito-idp.us-east-1.amazonaws.com/${var.cognito_user_pool_id}"
    : ""
  )

  hub_m2m_jwks_url = var.cognito_user_pool_id != "" ? "https://cognito-idp.us-east-1.amazonaws.com/${var.cognito_user_pool_id}/.well-known/jwks.json" : ""

  hub_m2m_token_url = var.cognito_auth_domain != "" ? "https://${trimsuffix(var.cognito_auth_domain, "/")}/oauth2/token" : ""

  hub_m2m_secret_name = contains(["prod", "platform"], var.environment) ? "cht-prod-cognito-m2m-hub" : "cht-${var.environment}-cognito-m2m-hub"

  outbound_m2m_secret_iam_arn = (
    var.platform_export_m2m_secret_arn == "" ? "" :
    startswith(var.platform_export_m2m_secret_arn, "arn:")
    ? var.platform_export_m2m_secret_arn
    : "arn:aws:secretsmanager:us-east-1:${data.aws_caller_identity.current.account_id}:secret:${var.platform_export_m2m_secret_arn}-*"
  )
}

module "hub_cognito" {
  count  = var.cognito_user_pool_id != "" ? 1 : 0
  source = "../../modules/identity/cognito-m2m"

  user_pool_id         = var.cognito_user_pool_id
  identifier           = "hub"
  name                 = "Content Hub API"
  scopes               = local.hub_m2m_scopes
  create_m2m_client    = false
  m2m_client_name      = "cht-hub-m2m-${var.environment}"
  m2m_outbound_scopes  = var.hub_m2m_outbound_scopes
  m2m_secret_name      = local.hub_m2m_secret_name
  token_url            = local.hub_m2m_token_url
  environment          = var.environment
}
