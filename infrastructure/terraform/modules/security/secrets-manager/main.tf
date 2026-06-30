locals {
  prefix = contains(["prod", "platform"], var.environment) ? var.project : "${var.project}-${var.environment}"
}

resource "aws_secretsmanager_secret" "app" {
  name = "${local.prefix}-app-secrets"
}

resource "aws_secretsmanager_secret_version" "app" {
  secret_id = aws_secretsmanager_secret.app.id
  secret_string = jsonencode({
    public_api_key        = var.public_api_key
    webhook_api_key       = var.webhook_api_key
    jwt_secret            = var.jwt_secret
    internal_cache_secret = var.internal_cache_secret
  })
}
