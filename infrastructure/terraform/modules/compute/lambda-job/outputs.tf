output "function_name" {
  value = aws_lambda_function.this.function_name
}

output "function_arn" {
  value = aws_lambda_function.this.arn
}

output "security_group_id" {
  value = aws_security_group.lambda.id
}

output "sqs_queue_arn" {
  value = try(aws_sqs_queue.job[0].arn, null)
}

output "sqs_queue_url" {
  value = try(aws_sqs_queue.job[0].url, null)
}

output "iam_role_name" {
  value = aws_iam_role.lambda.name
}

output "iam_role_arn" {
  value = aws_iam_role.lambda.arn
}
