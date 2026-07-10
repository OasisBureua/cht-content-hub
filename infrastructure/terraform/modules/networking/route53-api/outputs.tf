output "zone_id" {
  value = aws_route53_zone.api.zone_id
}

output "zone_name" {
  value = aws_route53_zone.api.name
}

output "name_servers" {
  value = aws_route53_zone.api.name_servers
}

output "api_fqdn" {
  value = var.api_domain
}

output "failover_enabled" {
  value = var.enable_failover
}

output "primary_health_check_id" {
  description = "Route53 health check ID for primary ALB (null when failover disabled)."
  value       = var.enable_failover ? aws_route53_health_check.primary[0].id : null
}
