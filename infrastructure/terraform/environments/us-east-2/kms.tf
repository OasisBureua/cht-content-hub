module "kms" {
  source = "../../modules/security/kms-rds"

  name_prefix = local.dr_project
}
