# Cross-region ECR replication (configured in the primary/source region registry).
# Replicates repositories matching any of `repository_prefixes` to destination_region.
#
# WARNING: `aws_ecr_replication_configuration` is a per-account singleton. Applying
# from any repo that manages this resource REPLACES the whole account ruleset. If
# the CHT platform stack (cht-platform-tool) also manages its own filters, this
# module MUST include every prefix (e.g. cht-platform-, contenthub-) or the
# missing side's replication silently stops. The AWS-side rule was manually
# amended 2026-07-21 to add `contenthub-`; this module now codifies both filters.

data "aws_caller_identity" "current" {}

data "aws_ecr_repository" "repositories" {
  for_each = toset(var.repository_names)
  name     = each.value
}

resource "aws_ecr_replication_configuration" "main" {
  replication_configuration {
    rule {
      destination {
        region      = var.destination_region
        registry_id = data.aws_caller_identity.current.account_id
      }

      dynamic "repository_filter" {
        for_each = toset(var.repository_prefixes)
        content {
          filter      = repository_filter.value
          filter_type = "PREFIX_MATCH"
        }
      }
    }
  }
}
