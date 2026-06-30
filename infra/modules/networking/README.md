# infra/modules/networking/

Network infrastructure.

- `vpc/` — VPC, subnets, NAT, security group baseline (or data source if sharing CHT's VPC)
- `alb/` — Application Load Balancer for the producer API
- `cloudfront/` — CloudFront distribution for the Content Hub SPA
- `route53/` — Route53 records (if delegated from GoDaddy; otherwise CNAMEs at GoDaddy)
