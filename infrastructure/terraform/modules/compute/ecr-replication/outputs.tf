output "dr_registry_url" {
  description = "ECR registry URL in the destination region."
  value       = "${data.aws_caller_identity.current.account_id}.dkr.ecr.${var.destination_region}.amazonaws.com"
}

output "replicated_repository_names" {
  description = "Repository names covered by the replication rule."
  value       = var.repository_names
}
