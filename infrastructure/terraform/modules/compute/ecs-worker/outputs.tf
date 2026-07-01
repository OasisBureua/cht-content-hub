output "security_group_id" {
  value = length(var.security_group_ids) > 0 ? var.security_group_ids[0] : aws_security_group.worker[0].id
}

output "service_name" {
  value = aws_ecs_service.worker.name
}
