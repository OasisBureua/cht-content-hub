# DR ALB lookup for Route53 failover (us-east-1 stack).
# Uses live AWS API — no dependency on us-east-2 state outputs (e.g. api_alb_zone_id).

provider "aws" {
  alias  = "use2"
  region = "us-east-2"

  default_tags {
    tags = {
      Project     = var.project
      Environment = var.environment
      Region      = "us-east-2"
      ManagedBy   = "Terraform"
    }
  }
}

data "aws_lb" "dr_api" {
  count    = var.enable_route53_failover ? 1 : 0
  provider = aws.use2
  name     = "${var.project}-dr-use2-api-alb"
}

locals {
  route53_failover_secondary_alb_dns_name = var.enable_route53_failover ? data.aws_lb.dr_api[0].dns_name : ""
  route53_failover_secondary_alb_zone_id  = var.enable_route53_failover ? data.aws_lb.dr_api[0].zone_id : ""
}
