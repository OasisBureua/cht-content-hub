output "bucket_name" {
  value = aws_s3_bucket.assets.id
}

output "bucket_arn" {
  value = aws_s3_bucket.assets.arn
}

output "assets_base_url" {
  description = "Public HTTPS base for kol-headshots (virtual-hosted–style S3 URL)"
  value       = "https://${aws_s3_bucket.assets.bucket_regional_domain_name}"
}

output "kol_headshots_base_url" {
  description = "Prefix URL for KOL headshot PNGs — use in kols.photo_url"
  value       = "https://${aws_s3_bucket.assets.bucket_regional_domain_name}/kol-headshots"
}
