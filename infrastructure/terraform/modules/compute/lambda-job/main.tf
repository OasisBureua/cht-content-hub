locals {
  prefix = contains(["prod", "platform"], var.environment) ? var.project : "${var.project}-${var.environment}"
  name   = "${local.prefix}-sync-${replace(var.job_name, "_", "-")}"
}

resource "aws_security_group" "lambda" {
  name        = "${local.name}-sg"
  description = "Sync Lambda ${var.job_name} (${var.environment})"
  vpc_id      = var.vpc_id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "${local.name}-sg"
    Environment = var.environment
    Job         = var.job_name
  }
}

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda" {
  name               = "${local.name}-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy_attachment" "lambda_vpc" {
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

resource "aws_iam_role_policy" "lambda_secrets" {
  name = "${local.name}-secrets"
  role = aws_iam_role.lambda.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue"]
      Resource = [var.database_secret_arn, var.app_secrets_arn]
    }]
  })
}

resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${local.name}"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "this" {
  function_name = local.name
  role          = aws_iam_role.lambda.arn
  handler       = var.handler
  runtime       = "python3.12"
  timeout       = var.timeout
  memory_size   = var.memory_size

  filename         = var.deployment_package_path
  source_code_hash = filebase64sha256(var.deployment_package_path)

  reserved_concurrent_executions = var.reserved_concurrent_executions >= 0 ? var.reserved_concurrent_executions : null

  vpc_config {
    subnet_ids         = var.private_subnet_ids
    security_group_ids = [aws_security_group.lambda.id]
  }

  environment {
    variables = merge(
      {
        CONTENTHUB_SERVICE_ROLE = "sync-lambda"
        ENVIRONMENT             = var.environment
        DATABASE_SECRET_ARN     = var.database_secret_arn
        APP_SECRETS_ARN         = var.app_secrets_arn
      },
      var.cht_cache_clear_url != "" ? { CHT_CACHE_CLEAR_URL = var.cht_cache_clear_url } : {}
    )
  }

  depends_on = [
    aws_iam_role_policy_attachment.lambda_basic,
    aws_iam_role_policy_attachment.lambda_vpc,
    aws_cloudwatch_log_group.lambda,
  ]

  tags = {
    Name        = local.name
    Environment = var.environment
    Job         = var.job_name
  }
}

# ── Optional SQS queue (long / serial jobs) ───────────────────────────────────

resource "aws_sqs_queue" "dlq" {
  count = var.sqs_trigger ? 1 : 0

  name                      = "${local.name}-dlq"
  message_retention_seconds = 1209600

  tags = {
    Name        = "${local.name}-dlq"
    Environment = var.environment
    Job         = var.job_name
  }
}

resource "aws_sqs_queue" "job" {
  count = var.sqs_trigger ? 1 : 0

  name                       = "${local.name}-queue"
  visibility_timeout_seconds = var.timeout + 30
  receive_wait_time_seconds  = 10

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq[0].arn
    maxReceiveCount     = 3
  })

  tags = {
    Name        = "${local.name}-queue"
    Environment = var.environment
    Job         = var.job_name
  }
}

resource "aws_iam_role_policy" "lambda_sqs" {
  count = var.sqs_trigger ? 1 : 0

  name = "${local.name}-sqs"
  role = aws_iam_role.lambda.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "sqs:ReceiveMessage",
        "sqs:DeleteMessage",
        "sqs:GetQueueAttributes",
        "sqs:ChangeMessageVisibility",
      ]
      Resource = aws_sqs_queue.job[0].arn
    }]
  })
}

resource "aws_lambda_event_source_mapping" "sqs" {
  count = var.sqs_trigger ? 1 : 0

  event_source_arn                   = aws_sqs_queue.job[0].arn
  function_name                      = aws_lambda_function.this.arn
  batch_size                         = 1
  maximum_batching_window_in_seconds = 5
  enabled                            = var.enabled

  depends_on = [aws_iam_role_policy.lambda_sqs]
}

# ── EventBridge schedule ──────────────────────────────────────────────────────

resource "aws_cloudwatch_event_rule" "schedule" {
  count = var.schedule_expression != null ? 1 : 0

  name                = "${local.name}-schedule"
  description         = "Trigger sync job ${var.job_name} (${var.environment})"
  schedule_expression = var.schedule_expression
  state               = var.enabled ? "ENABLED" : "DISABLED"

  tags = {
    Name        = "${local.name}-schedule"
    Environment = var.environment
    Job         = var.job_name
  }
}

data "aws_iam_policy_document" "eventbridge_assume" {
  count = var.schedule_expression != null ? 1 : 0

  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "eventbridge" {
  count = var.schedule_expression != null ? 1 : 0

  name               = "${local.name}-events-role"
  assume_role_policy = data.aws_iam_policy_document.eventbridge_assume[0].json
}

resource "aws_iam_role_policy" "eventbridge_invoke_lambda" {
  count = var.schedule_expression != null && !var.sqs_trigger ? 1 : 0

  name = "${local.name}-invoke-lambda"
  role = aws_iam_role.eventbridge[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["lambda:InvokeFunction"]
      Resource = aws_lambda_function.this.arn
    }]
  })
}

resource "aws_iam_role_policy" "eventbridge_send_sqs" {
  count = var.schedule_expression != null && var.sqs_trigger ? 1 : 0

  name = "${local.name}-send-sqs"
  role = aws_iam_role.eventbridge[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["sqs:SendMessage"]
      Resource = aws_sqs_queue.job[0].arn
    }]
  })
}

resource "aws_cloudwatch_event_target" "lambda" {
  count = var.schedule_expression != null && !var.sqs_trigger ? 1 : 0

  rule      = aws_cloudwatch_event_rule.schedule[0].name
  target_id = "Lambda"
  arn       = aws_lambda_function.this.arn
  role_arn  = aws_iam_role.eventbridge[0].arn

  input = jsonencode({ job = var.job_name, source = "eventbridge" })
}

resource "aws_lambda_permission" "eventbridge" {
  count = var.schedule_expression != null && !var.sqs_trigger ? 1 : 0

  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.this.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.schedule[0].arn
}

resource "aws_cloudwatch_event_target" "sqs" {
  count = var.schedule_expression != null && var.sqs_trigger ? 1 : 0

  rule      = aws_cloudwatch_event_rule.schedule[0].name
  target_id = "Sqs"
  arn       = aws_sqs_queue.job[0].arn
  role_arn  = aws_iam_role.eventbridge[0].arn

  input = jsonencode({ job = var.job_name, source = "eventbridge" })
}

data "aws_iam_policy_document" "sqs_eventbridge" {
  count = var.schedule_expression != null && var.sqs_trigger ? 1 : 0

  statement {
    sid    = "AllowEventBridgeSend"
    effect = "Allow"
    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.job[0].arn]
    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [aws_cloudwatch_event_rule.schedule[0].arn]
    }
  }
}

resource "aws_sqs_queue_policy" "eventbridge" {
  count = var.schedule_expression != null && var.sqs_trigger ? 1 : 0

  queue_url = aws_sqs_queue.job[0].id
  policy    = data.aws_iam_policy_document.sqs_eventbridge[0].json
}
