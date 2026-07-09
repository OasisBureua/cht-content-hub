output "security_group_id" {
  value = aws_security_group.api.id
}

output "service_name" {
  value = try(aws_ecs_service.api[0].name, null)
}

output "service_created" {
  value = var.create_service
}
