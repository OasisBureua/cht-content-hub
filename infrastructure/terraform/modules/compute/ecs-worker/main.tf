locals {
  prefix              = contains(["prod", "platform"], var.environment) ? var.project : "${var.project}-${var.environment}"
  worker_security_sgs = length(var.security_group_ids) > 0 ? var.security_group_ids : [aws_security_group.worker[0].id]
}

resource "aws_security_group" "worker" {
  count       = length(var.security_group_ids) > 0 ? 0 : 1
  name        = "${local.prefix}-worker-sg"
  description = "contenthub-worker ECS tasks"
  vpc_id      = var.vpc_id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "${local.prefix}-worker-sg"
    Environment = var.environment
  }
}

resource "aws_ecs_task_definition" "worker" {
  family                   = "${local.prefix}-worker"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.task_cpu
  memory                   = var.task_memory
  execution_role_arn       = var.execution_role_arn
  task_role_arn            = var.task_role_arn

  container_definitions = jsonencode([
    {
      name      = "contenthub-worker"
      image     = var.container_image
      essential = true
      environment = concat(
        [
          { name = "CONTENTHUB_SERVICE_ROLE", value = "worker" },
          { name = "AWS_REGION", value = var.aws_region },
        ],
        var.redis_url != "" ? [{ name = "REDIS_URL", value = var.redis_url }] : [],
        var.cht_cache_clear_url != "" ? [{ name = "CHT_CACHE_CLEAR_URL", value = var.cht_cache_clear_url }] : []
      )
      secrets = [
        { name = "DATABASE_URL", valueFrom = "${var.database_secret_arn}:url::" },
        { name = "INTERNAL_CACHE_SECRET", valueFrom = "${var.app_secrets_arn}:internal_cache_secret::" },
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = var.log_group_name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "worker"
        }
      }
    }
  ])
}

resource "aws_ecs_service" "worker" {
  name            = "${local.prefix}-worker"
  cluster         = var.cluster_id
  task_definition = aws_ecs_task_definition.worker.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = local.worker_security_sgs
    assign_public_ip = false
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
}
