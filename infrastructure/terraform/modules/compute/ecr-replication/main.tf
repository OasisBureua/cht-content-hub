# Cross-region ECR replication (configured in the primary/source region registry).
# Replicates repositories matching repository_prefix to destination_region.

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

      repository_filter {
        filter      = var.repository_prefix
        filter_type = "PREFIX_MATCH"
      }
    }
  }
}
