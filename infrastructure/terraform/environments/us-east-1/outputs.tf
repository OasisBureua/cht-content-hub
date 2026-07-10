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

output "api_alb_security_group_id" {
  description = "Hub API ALB security group ID"
  value       = module.alb_api.alb_security_group_id
}

output "api_waf_web_acl_arn" {
  description = "Regional WAF Web ACL ARN (null when enable_waf = false)"
  value       = var.enable_waf ? module.waf_alb[0].web_acl_arn : null
}

output "route53_zone_id" {
  description = "Hosted zone for api_domain (null when manage_route53 = false)"
  value       = var.manage_route53 ? module.route53_api[0].zone_id : null
}

output "route53_nameservers" {
  description = "Delegate these NS records in GoDaddy for the api_domain subdomain"
  value       = var.manage_route53 ? module.route53_api[0].name_servers : []
}

output "route53_failover_enabled" {
  description = "Whether PRIMARY/SECONDARY failover records are active for api_domain"
  value       = var.manage_route53 ? module.route53_api[0].failover_enabled : false
}

output "route53_primary_health_check_id" {
  description = "Route53 health check ID for primary ALB (null when failover disabled)"
  value       = var.manage_route53 ? module.route53_api[0].primary_health_check_id : null
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

    This delegates ${var.api_domain} to Route53 -> ALB -> ECS -> Aurora/RDS.

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
  value = local.aurora_app_active ? module.aurora_global[0].cluster_endpoint : (
    length(module.rds) > 0 ? module.rds[0].db_endpoint : null
  )
  sensitive = true
}

output "aurora_global_cluster_id" {
  description = "Aurora Global cluster identifier (null when enable_aurora_global = false)"
  value       = var.enable_aurora_global ? module.aurora_global[0].global_cluster_id : null
}

output "aurora_engine_version" {
  description = "Aurora PostgreSQL engine version"
  value       = var.enable_aurora_global ? var.aurora_engine_version : null
}

output "aurora_cluster_endpoint" {
  description = "Aurora writer endpoint (null when enable_aurora_global = false)"
  value       = var.enable_aurora_global ? module.aurora_global[0].cluster_endpoint : null
  sensitive   = true
}

output "aurora_reader_endpoint" {
  description = "Aurora regional reader endpoint"
  value       = var.enable_aurora_global ? module.aurora_global[0].cluster_reader_endpoint : null
  sensitive   = true
}

output "database_secret_arn" {
  value = local.database_secret_arn
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

output "ecr_dr_registry_url" {
  description = "Regional ECR registry in the DR region (images replicated from us-east-1 when enable_ecr_replication = true)."
  value       = try(module.ecr_replication[0].dr_registry_url, null)
}
