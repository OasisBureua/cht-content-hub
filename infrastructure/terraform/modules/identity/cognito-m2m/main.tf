# Hub owns this resource server. Other services own theirs (e.g. platform).
# Hub's M2M client requests *their* scopes, never hub/*.

resource "aws_cognito_resource_server" "this" {
  identifier   = var.identifier
  name         = var.name
  user_pool_id = var.user_pool_id

  dynamic "scope" {
    for_each = var.scopes
    content {
      scope_name        = scope.value.name
      scope_description = scope.value.description
    }
  }
}

resource "aws_cognito_user_pool_client" "m2m" {
  count = var.create_m2m_client ? 1 : 0

  name         = var.m2m_client_name
  user_pool_id = var.user_pool_id

  generate_secret                      = true
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["client_credentials"]
  allowed_oauth_scopes                 = var.m2m_outbound_scopes
  supported_identity_providers         = ["COGNITO"]
  prevent_user_existence_errors        = "ENABLED"

  depends_on = [aws_cognito_resource_server.this]
}

resource "aws_secretsmanager_secret" "m2m" {
  count = var.create_m2m_client && var.m2m_secret_name != "" ? 1 : 0

  name                    = var.m2m_secret_name
  description             = "Hub outbound M2M (${var.environment})"
  recovery_window_in_days = var.environment == "prod" ? 30 : 7

  tags = {
    Name        = var.m2m_secret_name
    Environment = var.environment
  }
}

resource "aws_secretsmanager_secret_version" "m2m" {
  count = length(aws_secretsmanager_secret.m2m)

  secret_id = aws_secretsmanager_secret.m2m[0].id
  secret_string = jsonencode({
    client_id     = aws_cognito_user_pool_client.m2m[0].id
    client_secret = aws_cognito_user_pool_client.m2m[0].client_secret
    token_url     = var.token_url
    scope         = join(" ", var.m2m_outbound_scopes)
  })
}
