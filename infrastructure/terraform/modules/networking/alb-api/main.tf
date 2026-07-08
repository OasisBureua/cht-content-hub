locals {
  prefix = contains(["prod", "platform"], var.environment) ? var.project : "${var.project}-${var.environment}"

  # Normalize bare IPs to /32 for stable for_each keys and AWS rule matching.
  allowed_ingress_cidrs = toset([
    for cidr in var.allowed_ingress_cidr_blocks :
    length(regexall("/", cidr)) > 0 ? cidr : "${cidr}/32"
  ])
}

resource "aws_security_group" "alb" {
  name        = "${local.prefix}-api-alb-sg"
  description = "Internet-facing ALB for contenthub-api (CHT consumer)"
  vpc_id      = var.vpc_id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "${local.prefix}-api-alb-sg"
    Environment = var.environment
  }
}

resource "aws_vpc_security_group_ingress_rule" "https_public" {
  count = var.allow_public_ingress ? 1 : 0

  description       = "HTTPS from internet"
  security_group_id = aws_security_group.alb.id
  cidr_ipv4         = "0.0.0.0/0"
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
}

resource "aws_vpc_security_group_ingress_rule" "http_public" {
  count = var.allow_public_ingress ? 1 : 0

  description       = "HTTP from internet (redirect to HTTPS when cert configured)"
  security_group_id = aws_security_group.alb.id
  cidr_ipv4         = "0.0.0.0/0"
  from_port         = 80
  to_port           = 80
  ip_protocol       = "tcp"
}

resource "aws_vpc_security_group_ingress_rule" "https_from_consumer_sgs" {
  for_each = toset(var.allowed_ingress_security_group_ids)

  description                  = "HTTPS from allowed consumer security groups"
  security_group_id            = aws_security_group.alb.id
  referenced_security_group_id = each.value
  from_port                    = 443
  to_port                      = 443
  ip_protocol                  = "tcp"
}

resource "aws_vpc_security_group_ingress_rule" "http_from_consumer_sgs" {
  for_each = toset(var.allowed_ingress_security_group_ids)

  description                  = "HTTP from allowed consumer security groups"
  security_group_id            = aws_security_group.alb.id
  referenced_security_group_id = each.value
  from_port                    = 80
  to_port                      = 80
  ip_protocol                  = "tcp"
}

resource "aws_vpc_security_group_ingress_rule" "https_from_cidr" {
  for_each = local.allowed_ingress_cidrs

  description       = var.ingress_cidr_description
  security_group_id = aws_security_group.alb.id
  cidr_ipv4         = each.value
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
}

resource "aws_lb" "main" {
  name               = "${local.prefix}-api-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = var.subnet_ids

  tags = {
    Name        = "${local.prefix}-api-alb"
    Environment = var.environment
  }
}

resource "aws_lb_target_group" "api" {
  name        = "${local.prefix}-api-tg"
  port        = var.api_port
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

  health_check {
    path    = "/health"
    matcher = "200"
  }
}

resource "aws_lb_listener" "http_forward" {
  count = var.certificate_arn == "" ? 1 : 0

  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
}

resource "aws_lb_listener" "http_redirect" {
  count = var.certificate_arn != "" ? 1 : 0

  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "redirect"
    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}

resource "aws_lb_listener" "https" {
  count = var.certificate_arn != "" ? 1 : 0

  load_balancer_arn = aws_lb.main.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
}

locals {
  listener_arn = var.certificate_arn != "" ? aws_lb_listener.https[0].arn : aws_lb_listener.http_forward[0].arn
  api_scheme   = var.certificate_arn != "" ? "https" : "http"
  api_host     = var.api_domain != "" ? var.api_domain : aws_lb.main.dns_name
}
