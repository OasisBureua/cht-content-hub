locals {
  prefix = contains(["prod", "platform"], var.environment) ? var.project : "${var.project}-${var.environment}"
}

resource "aws_security_group" "alb" {
  name        = "${local.prefix}-api-alb-sg"
  description = "Internal ALB for mediahub-api"
  vpc_id      = var.vpc_id

  dynamic "ingress" {
    for_each = var.allowed_security_group_ids
    content {
      description     = "HTTP from allowed clients"
      from_port       = var.api_port
      to_port         = var.api_port
      protocol        = "tcp"
      security_groups = [ingress.value]
    }
  }

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

resource "aws_lb" "main" {
  name               = "${local.prefix}-api-alb"
  internal           = true
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

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = var.api_port
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
}
