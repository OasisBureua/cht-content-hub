output "app_secrets_arn" {
  value = aws_secretsmanager_secret.app.arn
}

output "app_secrets_version_id" {
  value = aws_secretsmanager_secret_version.app.id
}
