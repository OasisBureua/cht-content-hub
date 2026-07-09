# Content Hub — prod.github.tfvars
# Non-secret infra for GitHub Actions deploy-prod.yml (committed).
# Secrets: GitHub Environment "production" → TF_VAR_* (see .github/CI_CD.md).
#
# Fill vpc_id, subnets, SG, and acm_certificate_arn before the first prod deploy.

project     = "contenthub"
environment = "prod"
deploy_mode = "cht-vpc"

api_domain          = "contenthub.communityhealth.media"
acm_certificate_arn = ""

vpc_id = "vpc-xxxxxxxx"
private_subnet_ids = [
  "subnet-aaaaaaaa",
  "subnet-bbbbbbbb",
]
public_subnet_ids = [
  "subnet-cccccccc",
  "subnet-dddddddd",
]

cht_backend_security_group_id = "sg-xxxxxxxx"
cht_nat_gateway_cidr_blocks   = []
alb_allow_public_ingress      = true
enable_waf                    = true

# Overridden per deploy by workflow (-var api_image)
api_image = "233636046512.dkr.ecr.us-east-1.amazonaws.com/contenthub-api:1.0.0"

rds_instance_class    = "db.r6g.large"
rds_engine_version    = "15.17"
rds_allocated_storage = 100
rds_multi_az          = true
rds_backup_retention  = 30
log_retention_days    = 365

api_task_cpu      = 1024
api_task_memory   = 2048
api_desired_count = 2
api_min_capacity  = 2
api_max_capacity  = 6

worker_desired_count = 0

sync_jobs_enabled = {
  cache_clear            = false
  hcp_intel_poll         = false
  openalex_backfill      = false
  kol_hcp_matcher        = false
  post_tagging           = false
  playlist_doctor_tagger = false
}

cht_cache_clear_url = "https://contenthub.communityhealth.media/internal/cache/catalog/clear"
