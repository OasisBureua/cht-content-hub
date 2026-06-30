locals {
  prefix = contains(["prod", "platform"], var.environment) ? var.project : "${var.project}-${var.environment}"
}

resource "aws_security_group" "api" {
  name        = "${local.prefix}-api-sg"
  description = "mediahub-api ECS tasks"
  vpc_id      = var.vpc_id

  ingress {
    description     = "HTTP from API ALB"
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [var.alb_security_group_id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "${local.prefix}-api-sg"
    Environment = var.environment
  }
}

resource "aws_ecs_task_definition" "api" {
  family                   = "${local.prefix}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.task_cpu
  memory                   = var.task_memory
  execution_role_arn       = var.execution_role_arn
  task_role_arn            = var.task_role_arn

  container_definitions = jsonencode([
    {
      name      = "mediahub-api"
      image     = var.container_image
      essential = true
      portMappings = [{ containerPort = 8000, protocol = "tcp" }]
      environment = concat(
        [
          { name = "ENABLE_SCHEDULER", value = "false" },
          { name = "MEDIAHUB_SERVICE_ROLE", value = "api" },
          { name = "AWS_REGION", value = var.aws_region },
        ],
        var.redis_url != "" ? [{ name = "REDIS_URL", value = var.redis_url }] : []
      )
      secrets = [
        { name = "DATABASE_URL", valueFrom = "${var.database_secret_arn}:url::" },
        { name = "PUBLIC_API_KEY", valueFrom = "${var.app_secrets_arn}:public_api_key::" },
        { name = "WEBHOOK_API_KEY", valueFrom = "${var.app_secrets_arn}:webhook_api_key::" },
        { name = "JWT_SECRET", valueFrom = "${var.app_secrets_arn}:jwt_secret::" },
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = var.log_group_name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "api"
        }
      }
      healthCheck = {
        command     = ["CMD-SHELL", "curl -sf http://localhost:8000/health || exit 1"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 90
      }
    }
  ])
}

resource "aws_ecs_service" "api" {
  name            = "${local.prefix}-api"
  cluster         = var.cluster_id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [aws_security_group.api.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = var.target_group_arn
    container_name   = "mediahub-api"
    container_port   = 8000
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
}

resource "aws_appautoscaling_target" "api" {
  max_capacity       = var.max_capacity
  min_capacity       = var.min_capacity
  resource_id        = "service/${var.cluster_name}/${aws_ecs_service.api.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "api_cpu" {
  name               = "${local.prefix}-api-cpu"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.api.resource_id
  scalable_dimension = aws_appautoscaling_target.api.scalable_dimension
  service_namespace  = aws_appautoscaling_target.api.service_namespace

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
    target_value = 70
  }
}
