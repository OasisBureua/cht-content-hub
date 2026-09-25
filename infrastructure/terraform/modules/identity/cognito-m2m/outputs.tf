output "resource_server_identifier" {
  value = aws_cognito_resource_server.this.identifier
}

output "issuer" {
  value = "https://cognito-idp.${data.aws_region.current.name}.amazonaws.com/${var.user_pool_id}"
}

output "m2m_client_id" {
  value = try(aws_cognito_user_pool_client.m2m[0].id, "")
}

output "m2m_secret_arn" {
  value = try(aws_secretsmanager_secret.m2m[0].arn, "")
}

data "aws_region" "current" {}
