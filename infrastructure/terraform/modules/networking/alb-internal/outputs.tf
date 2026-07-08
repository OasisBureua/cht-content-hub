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
  value = aws_lb_listener.http.arn
}

output "api_internal_url" {
  value = "http://${aws_lb.main.dns_name}:${var.api_port}"
}
