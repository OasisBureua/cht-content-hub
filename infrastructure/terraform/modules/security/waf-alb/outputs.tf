output "web_acl_arn" {
  value = aws_wafv2_web_acl.alb.arn
}

output "web_acl_id" {
  value = aws_wafv2_web_acl.alb.id
}

output "web_acl_name" {
  value = aws_wafv2_web_acl.alb.name
}
