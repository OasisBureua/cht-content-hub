# Hub's Cognito resource server on the shared CHT pool.
# Does not create Hub's outbound client (create_m2m_client = false).
# Optionally parks cht-reports-m2m (hub/reports.read) until reports has its own TF.
# Does not create cht-platform-m2m (platform TF). No-op until cognito_user_pool_id is set.

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

  reports_m2m_env_label   = contains(["prod", "platform"], var.environment) ? "prod" : var.environment
  reports_m2m_enabled     = var.cognito_user_pool_id != "" && var.enable_reports_m2m_client
  reports_m2m_client_name = "cht-reports-m2m-${local.reports_m2m_env_label}"
  reports_m2m_secret_name = "cht-${local.reports_m2m_env_label}-cognito-m2m-reports"
  reports_m2m_scope       = "hub/reports.read"

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

  user_pool_id        = var.cognito_user_pool_id
  identifier          = "hub"
  name                = "Content Hub API"
  scopes              = local.hub_m2m_scopes
  create_m2m_client   = false
  m2m_client_name     = "cht-hub-m2m-${var.environment}"
  m2m_outbound_scopes = var.hub_m2m_outbound_scopes
  m2m_secret_name     = local.hub_m2m_secret_name
  token_url           = local.hub_m2m_token_url
  environment         = var.environment
}

# Reports → Hub. Create (nothing to import: client + secret are not in AWS).
# Allowed scope is hub/reports.read only; RS already defines reports.read.
resource "aws_cognito_user_pool_client" "reports_m2m" {
  count = local.reports_m2m_enabled ? 1 : 0

  name         = local.reports_m2m_client_name
  user_pool_id = var.cognito_user_pool_id

  generate_secret                      = true
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["client_credentials"]
  allowed_oauth_scopes                 = [local.reports_m2m_scope]
  supported_identity_providers         = ["COGNITO"]
  prevent_user_existence_errors        = "ENABLED"

  token_validity_units {
    access_token = "hours"
  }
  access_token_validity = 1

  depends_on = [module.hub_cognito]
}

resource "aws_secretsmanager_secret" "reports_m2m" {
  count = local.reports_m2m_enabled ? 1 : 0

  name                    = local.reports_m2m_secret_name
  description             = "Cognito M2M for cht-reports → Hub (${local.reports_m2m_scope}). Client ${local.reports_m2m_client_name}."
  recovery_window_in_days = var.environment == "prod" ? 30 : 7

  tags = {
    Name        = local.reports_m2m_secret_name
    Environment = var.environment
  }
}

resource "aws_secretsmanager_secret_version" "reports_m2m" {
  count = local.reports_m2m_enabled ? 1 : 0

  secret_id = aws_secretsmanager_secret.reports_m2m[0].id
  secret_string = jsonencode({
    client_id     = aws_cognito_user_pool_client.reports_m2m[0].id
    client_secret = aws_cognito_user_pool_client.reports_m2m[0].client_secret
    token_url     = local.hub_m2m_token_url
    scope         = local.reports_m2m_scope
  })
}
