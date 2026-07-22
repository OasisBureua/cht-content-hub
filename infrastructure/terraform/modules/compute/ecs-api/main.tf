locals {
  prefix = contains(["prod", "platform"], var.environment) ? var.project : "${var.project}-${var.environment}"

  app_secret_env = [
    { name = "PUBLIC_API_KEY", key = "public_api_key" },
    { name = "WEBHOOK_API_KEY", key = "webhook_api_key" },
    { name = "JWT_SECRET", key = "jwt_secret" },
    { name = "INTERNAL_CACHE_SECRET", key = "internal_cache_secret" },
    { name = "OPENAI_API_KEY", key = "openai_api_key" },
    { name = "ANTHROPIC_API_KEY", key = "anthropic_api_key" },
    { name = "LINKEDIN_CLIENT_ID", key = "linkedin_client_id" },
    { name = "LINKEDIN_CLIENT_SECRET", key = "linkedin_client_secret" },
    { name = "LINKEDIN_REDIRECT_URI", key = "linkedin_redirect_uri" },
    { name = "LINKEDIN_SCOPES", key = "linkedin_scopes" },
    { name = "LINKEDIN_ORG_URN", key = "linkedin_org_urn" },
    { name = "LINKEDIN_AD_ACCOUNT_ID", key = "linkedin_ad_account_id" },
    { name = "LINKEDIN_ADS_ACCESS_TOKEN", key = "linkedin_ads_access_token" },
    { name = "LINKEDIN_ADS_CLIENT_ID", key = "linkedin_ads_client_id" },
    { name = "LINKEDIN_ADS_CLIENT_SECRET", key = "linkedin_ads_client_secret" },
    { name = "LINKEDIN_ADS_REDIRECT_URI", key = "linkedin_ads_redirect_uri" },
    { name = "LINKEDIN_ADS_SCOPES", key = "linkedin_ads_scopes" },
    { name = "YOUTUBE_API_KEY", key = "youtube_api_key" },
    { name = "YOUTUBE_CHANNEL_ID", key = "youtube_channel_id" },
    { name = "YOUTUBE_CHANNEL_HANDLE", key = "youtube_channel_handle" },
    { name = "X_BEARER_TOKEN", key = "x_bearer_token" },
    { name = "X_ACCOUNT_HANDLE", key = "x_account_handle" },
    { name = "WORDPRESS_WEBHOOK_SECRET", key = "wordpress_webhook_secret" },
  ]
}

resource "aws_security_group" "api" {
  name        = "${local.prefix}-api-sg"
  description = "contenthub-api ECS tasks"
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
      name         = "contenthub-api"
      image        = var.container_image
      essential    = true
      portMappings = [{ containerPort = 8000, protocol = "tcp" }]
      environment = concat(
        [
          { name = "CONTENTHUB_SERVICE_ROLE", value = "api" },
          { name = "AWS_REGION", value = var.aws_region },
          { name = "ENVIRONMENT", value = var.environment },
          { name = "APP_VERSION", value = var.app_version },
          { name = "CONTAINER_IMAGE", value = var.container_image },
        ],
        var.redis_url != "" ? [{ name = "REDIS_URL", value = var.redis_url }] : [],
        var.wordpress_events_queue_url != "" ? [{ name = "WORDPRESS_EVENTS_QUEUE_URL", value = var.wordpress_events_queue_url }] : [],
        var.hcp_intel_poll_queue_url != "" ? [{ name = "HCP_INTEL_POLL_QUEUE_URL", value = var.hcp_intel_poll_queue_url }] : [],
        var.assets_bucket != "" ? [{ name = "ASSETS_BUCKET", value = var.assets_bucket }] : [],
      )
      secrets = concat(
        [
          { name = "DATABASE_URL", valueFrom = "${var.database_secret_arn}:url::" },
        ],
        [
          for item in local.app_secret_env : {
            name      = item.name
            valueFrom = "${var.app_secrets_arn}:${item.key}::"
          }
        ],
      )
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = var.log_group_name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "api"
        }
      }
      healthCheck = {
        command     = ["CMD-SHELL", "curl -sf http://localhost:8000/health/live || exit 1"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 90
      }
    }
  ])
}

resource "aws_ecs_service" "api" {
  count = var.create_service ? 1 : 0

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
    container_name   = "contenthub-api"
    container_port   = 8000
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
}

resource "aws_appautoscaling_target" "api" {
  count = var.create_service ? 1 : 0

  max_capacity       = var.max_capacity
  min_capacity       = var.min_capacity
  resource_id        = "service/${var.cluster_name}/${aws_ecs_service.api[0].name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "api_cpu" {
  count = var.create_service ? 1 : 0

  name               = "${local.prefix}-api-cpu"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.api[0].resource_id
  scalable_dimension = aws_appautoscaling_target.api[0].scalable_dimension
  service_namespace  = aws_appautoscaling_target.api[0].service_namespace

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
    target_value = 70
  }
}
