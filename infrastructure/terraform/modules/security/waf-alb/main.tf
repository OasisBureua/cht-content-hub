locals {
  prefix = contains(["prod", "platform"], var.environment) ? var.project : "${var.project}-${var.environment}"
}

resource "aws_wafv2_web_acl" "alb" {
  name        = "${local.prefix}-api-alb-waf"
  description = "Regional WAF for Content Hub API ALB - ${local.prefix}"
  scope       = "REGIONAL"

  default_action {
    allow {}
  }

  dynamic "rule" {
    for_each = var.enable_rate_limit ? [1] : []
    content {
      name     = "${local.prefix}-rate-limit"
      priority = 1

      action {
        block {}
      }

      statement {
        rate_based_statement {
          limit              = var.rate_limit_count
          aggregate_key_type = "IP"
        }
      }

      visibility_config {
        cloudwatch_metrics_enabled = true
        metric_name                = "${local.prefix}-rate-limit"
        sampled_requests_enabled   = true
      }
    }
  }

  dynamic "rule" {
    for_each = var.enable_managed_rules ? [1] : []
    content {
      name     = "${local.prefix}-ip-reputation"
      priority = 2

      override_action {
        none {}
      }

      statement {
        managed_rule_group_statement {
          vendor_name = "AWS"
          name        = "AWSManagedRulesAmazonIpReputationList"
        }
      }

      visibility_config {
        cloudwatch_metrics_enabled = true
        metric_name                = "${local.prefix}-ip-reputation"
        sampled_requests_enabled   = true
      }
    }
  }

  dynamic "rule" {
    for_each = var.enable_managed_rules ? [1] : []
    content {
      name     = "${local.prefix}-known-bad-inputs"
      priority = 3

      override_action {
        none {}
      }

      statement {
        managed_rule_group_statement {
          vendor_name = "AWS"
          name        = "AWSManagedRulesKnownBadInputsRuleSet"
        }
      }

      visibility_config {
        cloudwatch_metrics_enabled = true
        metric_name                = "${local.prefix}-known-bad-inputs"
        sampled_requests_enabled   = true
      }
    }
  }

  dynamic "rule" {
    for_each = var.enable_common_rule_set ? [1] : []
    content {
      name     = "${local.prefix}-aws-common-rules"
      priority = 4

      override_action {
        none {}
      }

      statement {
        managed_rule_group_statement {
          vendor_name = "AWS"
          name        = "AWSManagedRulesCommonRuleSet"
        }
      }

      visibility_config {
        cloudwatch_metrics_enabled = true
        metric_name                = "${local.prefix}-aws-common-rules"
        sampled_requests_enabled   = true
      }
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "${local.prefix}-api-alb-waf"
    sampled_requests_enabled   = true
  }

  tags = {
    Name        = "${local.prefix}-api-alb-waf"
    Environment = var.environment
  }
}

resource "aws_wafv2_web_acl_association" "alb" {
  resource_arn = var.alb_arn
  web_acl_arn  = aws_wafv2_web_acl.alb.arn
}
