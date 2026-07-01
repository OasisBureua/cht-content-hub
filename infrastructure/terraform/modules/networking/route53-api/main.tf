locals {
  prefix = contains(["prod", "platform"], var.environment) ? var.project : "${var.project}-${var.environment}"
}

# Dedicated zone per API hostname (devhub.* / contenthub.*) — delegate NS from GoDaddy parent zone.
resource "aws_route53_zone" "api" {
  name = var.api_domain

  tags = {
    Name        = "${local.prefix}-api-zone"
    Environment = var.environment
    Purpose     = "Content Hub producer API - ALB alias until CloudFront and S3 frontend"
  }
}

resource "aws_route53_record" "api_apex" {
  zone_id = aws_route53_zone.api.zone_id
  name    = ""
  type    = "A"

  alias {
    name                   = var.alb_dns_name
    zone_id                = var.alb_zone_id
    evaluate_target_health = true
  }
}
