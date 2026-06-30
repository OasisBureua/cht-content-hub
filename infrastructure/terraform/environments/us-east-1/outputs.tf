output "vpc_id" {
  value = var.vpc_id
}

output "api_base_url" {
  description = "CHT CONTENTHUB_BASE_URL = <this>/api/public"
  value       = module.alb_api.api_base_url
}

output "api_alb_dns_name" {
  value = module.alb_api.alb_dns_name
}

output "route53_zone_id" {
  description = "Hosted zone for api_domain (null when manage_route53 = false)"
  value       = var.manage_route53 ? module.route53_api[0].zone_id : null
}

output "route53_nameservers" {
  description = "Delegate these NS records in GoDaddy for the api_domain subdomain"
  value       = var.manage_route53 ? module.route53_api[0].name_servers : []
}

output "dns_delegation_hint" {
  description = "After apply: add NS delegation in GoDaddy parent zone (communityhealth.media)"
  value = var.manage_route53 ? join("\n", [
    "Subdomain: ${replace(var.api_domain, ".communityhealth.media", "")}",
    "Type: NS",
    "Values:",
    join("\n", [for ns in module.route53_api[0].name_servers : "  ${ns}"]),
  ]) : "Route53 disabled (manage_route53 = false)"
}

locals {
  next_steps_route53 = <<-EOT

    Add NS records in GoDaddy (zone: communityhealth.media):

    Type: NS
    Name: ${replace(var.api_domain, ".communityhealth.media", "")}
    Value: Add 4 records, one per nameserver:
    ${join("\n    ", module.route53_api[0].name_servers)}

    This delegates ${var.api_domain} to Route53 -> ALB -> ECS -> RDS.

    CHT CONTENTHUB_BASE_URL: ${module.alb_api.api_base_url}/api/public
    Smoke test: ./scripts/smoke.sh https://${var.api_domain}
  EOT

  next_steps_manual_dns = <<-EOT

    Route53 disabled (manage_route53 = false). Point ${var.api_domain} at ALB manually:
    ${module.alb_api.alb_dns_name}

    CHT CONTENTHUB_BASE_URL: ${module.alb_api.api_base_url}/api/public
    Smoke test: ./scripts/smoke.sh https://${var.api_domain}
  EOT
}

output "next_steps" {
  description = "Post-deploy checklist (NS delegation, smoke test)"
  value       = var.manage_route53 ? local.next_steps_route53 : local.next_steps_manual_dns
}

output "cluster_name" {
  value = local.cluster_name
}

output "api_service_name" {
  value = module.ecs_api.service_name
}

output "worker_service_name" {
  value = var.worker_desired_count > 0 ? module.ecs_worker[0].service_name : null
}

output "rds_endpoint" {
  value     = module.rds.db_endpoint
  sensitive = true
}

output "database_secret_arn" {
  value = module.rds.database_secret_arn
}

output "assets_bucket_name" {
  value = module.s3_assets.bucket_name
}

output "kol_headshots_base_url" {
  description = "Base URL for kols.photo_url after headshot migration"
  value       = module.s3_assets.kol_headshots_base_url
}

output "sync_lambda_functions" {
  description = "Sync job Lambda function names (one per job per environment)"
  value       = { for name, mod in module.sync_lambda : name => mod.function_name }
}
