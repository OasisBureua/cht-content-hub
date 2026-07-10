output "global_cluster_id" {
  description = "Aurora Global cluster identifier"
  value       = var.role == "primary" ? aws_rds_global_cluster.this[0].id : var.global_cluster_identifier
}

output "global_cluster_arn" {
  description = "Aurora Global cluster ARN"
  value       = var.role == "primary" ? aws_rds_global_cluster.this[0].arn : null
}

output "cluster_id" {
  description = "Regional Aurora cluster identifier"
  value       = aws_rds_cluster.this.id
}

output "cluster_endpoint" {
  description = "Writer cluster endpoint (primary) or local cluster endpoint"
  value       = aws_rds_cluster.this.endpoint
}

output "cluster_reader_endpoint" {
  description = "Reader endpoint for the regional cluster"
  value       = aws_rds_cluster.this.reader_endpoint
}

output "cluster_address" {
  description = "Writer hostname without port"
  value       = aws_rds_cluster.this.endpoint
}

output "cluster_port" {
  description = "Database port"
  value       = aws_rds_cluster.this.port
}

output "database_name" {
  description = "Database name"
  value       = var.database_name
}

output "master_username" {
  description = "Master username (primary cluster)"
  value       = var.role == "primary" ? var.master_username : null
  sensitive   = true
}

output "master_password" {
  description = "Master password (primary cluster)"
  value       = var.role == "primary" ? random_password.master[0].result : null
  sensitive   = true
}

output "connection_string" {
  description = "PostgreSQL URL for the writer endpoint (primary only)"
  value = var.role == "primary" ? (
    "postgresql://${var.master_username}:${urlencode(random_password.master[0].result)}@${aws_rds_cluster.this.endpoint}/${var.database_name}"
  ) : null
  sensitive = true
}

output "asyncpg_connection_string" {
  description = "Async SQLAlchemy URL for the writer endpoint (primary only)"
  value = var.role == "primary" ? (
    "postgresql+asyncpg://${var.master_username}:${urlencode(random_password.master[0].result)}@${aws_rds_cluster.this.endpoint}/${var.database_name}"
  ) : null
  sensitive = true
}

output "reader_host" {
  description = "Regional reader endpoint hostname"
  value       = aws_rds_cluster.this.reader_endpoint
}

output "security_group_id" {
  description = "Aurora security group ID"
  value       = aws_security_group.aurora.id
}

output "engine_version" {
  description = "Aurora PostgreSQL engine version"
  value       = var.engine_version
}
