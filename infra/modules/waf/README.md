# infra/modules/waf/

WAF web ACL module. Baseline AWS managed rule sets + custom rate limiting for the ALB fronting the ECS API. Inputs: rate-limit thresholds, IP allowlists. Outputs: web ACL ARN.
