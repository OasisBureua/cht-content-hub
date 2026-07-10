output "rds_kms_key_id" {
  value = aws_kms_key.rds.key_id
}

output "rds_kms_key_arn" {
  value = aws_kms_key.rds.arn
}
