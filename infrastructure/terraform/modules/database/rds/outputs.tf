output "db_endpoint" {
  value     = aws_db_instance.main.address
  sensitive = true
}

output "database_secret_arn" {
  value = aws_secretsmanager_secret.database.arn
}

output "security_group_id" {
  value = aws_security_group.rds.id
}
