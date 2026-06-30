# infra/modules/networking/alb/

Application Load Balancer fronting the producer ECS service.

## Inputs

- ALB name (`cht-content-hub-{env}-alb`)
- VPC + public subnet IDs
- ACM cert ARN for `*.contenthub.communityhealth.media`
- Target group definition (forwarded to ECS service)
- WAF web ACL ARN (regional)

## Outputs

- ALB DNS name
- Target group ARN (consumed by the ECS service module)
