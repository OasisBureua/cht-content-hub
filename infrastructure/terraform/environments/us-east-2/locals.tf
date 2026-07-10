# us-east-2 DR — maps prod tfvars (dr_* keys) to regional resources.
# environment stays "prod"; resource names use contenthub-dr-use2 (CHT pattern).

locals {
  dr_project         = "${var.project}-dr-use2"
  resource_prefix    = local.dr_project
  vpc_id             = var.dr_vpc_id
  private_subnet_ids = var.dr_private_subnet_ids
  public_subnet_ids  = var.dr_public_subnet_ids
  acm_certificate_arn = var.dr_acm_certificate_arn != "" ? var.dr_acm_certificate_arn : var.acm_certificate_arn

  log_retention  = coalesce(var.log_retention_days, 365)
  api_image      = var.dr_api_image != "" ? var.dr_api_image : var.api_image
  api_image_tag  = try(element(split(":", local.api_image), 1), "unknown")
  standby_scale  = var.dr_standby_scale_factor
  api_desired_dr = max(1, ceil(var.api_desired_count * local.standby_scale))
  api_min_dr     = max(1, floor(var.api_min_capacity * local.standby_scale))
  api_max_dr     = max(1, ceil(var.api_max_capacity * local.standby_scale))

  primary_aurora_global_cluster_id = try(
    tostring(data.terraform_remote_state.primary.outputs.aurora_global_cluster_id),
    ""
  )
  primary_aurora_engine_version = try(
    tostring(data.terraform_remote_state.primary.outputs.aurora_engine_version),
    var.aurora_engine_version
  )
  aurora_global_enabled = var.enable_aurora_global && local.primary_aurora_global_cluster_id != ""
}
