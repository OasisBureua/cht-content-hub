output "vpc_id" {
  value = var.vpc_id
}

output "api_base_url" {
  description = "CHT MEDIAHUB_BASE_URL = <this>/api/public"
  value       = module.alb_api.api_base_url
}

output "api_alb_dns_name" {
  value = module.alb_api.alb_dns_name
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
