locals {
  api_scheme = var.certificate_arn != "" ? "https" : "http"
  api_host   = var.api_domain != "" ? var.api_domain : aws_lb.main.dns_name
}

output "alb_arn" {
  value = aws_lb.main.arn
}

output "alb_dns_name" {
  value = aws_lb.main.dns_name
}

output "alb_security_group_id" {
  value = aws_security_group.alb.id
}

output "target_group_arn" {
  value = aws_lb_target_group.api.arn
}

output "listener_arn" {
  value = local.listener_arn
}

output "api_base_url" {
  description = "CHT MEDIAHUB_BASE_URL host — append /api/public (until /api migration)"
  value       = "${local.api_scheme}://${local.api_host}"
}
