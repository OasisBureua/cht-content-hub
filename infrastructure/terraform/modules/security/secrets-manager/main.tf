locals {
  prefix = contains(["prod", "platform"], var.environment) ? var.project : "${var.project}-${var.environment}"
}

resource "aws_secretsmanager_secret" "app" {
  name                    = "${local.prefix}-app-secrets"
  description             = "Application secrets for Content Hub ${var.environment}"
  kms_key_id              = var.kms_key_id != "" ? var.kms_key_id : null
  recovery_window_in_days = contains(["prod", "platform"], var.environment) ? 30 : 7

  dynamic "replica" {
    for_each = var.replica_regions
    content {
      region     = replica.value.region
      kms_key_id = try(replica.value.kms_key_id, null)
    }
  }

  tags = {
    Name        = "${local.prefix}-app-secrets"
    Environment = var.environment
  }
}

resource "aws_secretsmanager_secret_version" "app" {
  secret_id = aws_secretsmanager_secret.app.id
  secret_string = jsonencode({
    public_api_key             = var.public_api_key
    webhook_api_key            = var.webhook_api_key
    jwt_secret                 = var.jwt_secret
    internal_cache_secret      = var.internal_cache_secret
    openai_api_key             = var.openai_api_key
    anthropic_api_key          = var.anthropic_api_key
    linkedin_client_id         = var.linkedin_client_id
    linkedin_client_secret     = var.linkedin_client_secret
    linkedin_redirect_uri      = var.linkedin_redirect_uri
    linkedin_scopes            = var.linkedin_scopes
    linkedin_org_urn           = var.linkedin_org_urn
    linkedin_ad_account_id     = var.linkedin_ad_account_id
    linkedin_ads_access_token  = var.linkedin_ads_access_token
    linkedin_ads_client_id     = var.linkedin_ads_client_id
    linkedin_ads_client_secret = var.linkedin_ads_client_secret
    linkedin_ads_redirect_uri  = var.linkedin_ads_redirect_uri
    linkedin_ads_scopes        = var.linkedin_ads_scopes
    youtube_api_key            = var.youtube_api_key
    youtube_channel_id         = var.youtube_channel_id
    youtube_channel_handle     = var.youtube_channel_handle
    x_bearer_token             = var.x_bearer_token
    x_account_handle           = var.x_account_handle
    wordpress_webhook_secret   = var.wordpress_webhook_secret
  })
}
