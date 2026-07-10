output "vpc_id" {
  value = local.vpc_id
}

output "api_base_url" {
  description = "CHT CONTENTHUB_BASE_URL_SECONDARY = <this>/api/public"
  value       = module.alb_api.api_base_url
}

output "api_alb_dns_name" {
  value = module.alb_api.alb_dns_name
}

output "api_alb_zone_id" {
  description = "Route53 alias target zone ID for DR ALB (used by us-east-1 failover record)."
  value       = module.alb_api.alb_zone_id
}

output "cluster_name" {
  value = local.cluster_name
}

output "api_service_name" {
  value = module.ecs_api.service_name
}

output "database_secret_arn" {
  value = local.database_secret_arn
}

output "ecr_registry_url" {
  description = "Regional ECR registry (images replicated from us-east-1)."
  value       = "${data.aws_caller_identity.current.account_id}.dkr.ecr.us-east-2.amazonaws.com"
}

output "aurora_reader_endpoint" {
  value     = local.aurora_global_enabled ? module.aurora_global[0].reader_host : null
  sensitive = true
}
