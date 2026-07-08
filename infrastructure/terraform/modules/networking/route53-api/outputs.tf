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
