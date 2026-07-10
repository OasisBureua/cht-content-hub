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

# Single-record mode (dev / no DR secondary).
resource "aws_route53_record" "api_apex" {
  count = var.enable_failover ? 0 : 1

  zone_id = aws_route53_zone.api.zone_id
  name    = ""
  type    = "A"

  alias {
    name                   = var.alb_dns_name
    zone_id                = var.alb_zone_id
    evaluate_target_health = true
  }
}

# Failover mode: probe primary ALB directly (not api_domain) to avoid circular DNS dependency.
# HTTP :80 /health is forwarded on the ALB (not redirected) so target health is reflected.
resource "aws_route53_health_check" "primary" {
  count = var.enable_failover ? 1 : 0

  fqdn              = var.alb_dns_name
  port              = 80
  type              = "HTTP"
  resource_path     = "/health"
  failure_threshold = 3
  request_interval  = 30

  tags = {
    Name        = "${local.prefix}-api-primary-health"
    Environment = var.environment
  }
}

resource "aws_route53_record" "api_apex_primary" {
  count = var.enable_failover ? 1 : 0

  zone_id        = aws_route53_zone.api.zone_id
  name           = ""
  type           = "A"
  set_identifier = "primary-${var.primary_region}"

  failover_routing_policy {
    type = "PRIMARY"
  }

  health_check_id = aws_route53_health_check.primary[0].id

  alias {
    name                   = var.alb_dns_name
    zone_id                = var.alb_zone_id
    evaluate_target_health = true
  }
}

resource "aws_route53_record" "api_apex_secondary" {
  count = var.enable_failover ? 1 : 0

  zone_id        = aws_route53_zone.api.zone_id
  name           = ""
  type           = "A"
  set_identifier = "secondary-${var.secondary_region}"

  failover_routing_policy {
    type = "SECONDARY"
  }

  alias {
    name                   = var.secondary_alb_dns_name
    zone_id                = var.secondary_alb_zone_id
    evaluate_target_health = true
  }
}

resource "aws_cloudwatch_metric_alarm" "primary_down" {
  count = var.enable_failover && length(var.failover_alarm_actions) > 0 ? 1 : 0

  alarm_name          = "${local.prefix}-api-primary-region-down"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 2
  metric_name         = "HealthCheckStatus"
  namespace           = "AWS/Route53"
  period              = 60
  statistic           = "Minimum"
  threshold           = 1
  alarm_description   = "Content Hub API primary (${var.primary_region}) Route53 health check failing — traffic should fail over to ${var.secondary_region}"
  treat_missing_data  = "breaching"

  dimensions = {
    HealthCheckId = aws_route53_health_check.primary[0].id
  }

  alarm_actions = var.failover_alarm_actions
}
