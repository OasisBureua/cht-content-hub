# Content Hub — prod.github.tfvars
# Non-secret infra for GitHub Actions deploy-prod.yml (committed).
# Secrets: GitHub Environment "production" → TF_VAR_* (see .github/CI_CD.md).
#
# Fill vpc_id, subnets, SG, and acm_certificate_arn before the first prod deploy.

project     = "contenthub"
environment = "prod"
deploy_mode = "cht-vpc"

api_domain          = "contenthub.communityhealth.media"
acm_certificate_arn = "arn:aws:acm:us-east-1:233636046512:certificate/b58e05dd-fed0-4a6f-9ad9-6528dae4f39a"

vpc_id = "vpc-034141e3292f1f3fb"
private_subnet_ids = [
  "subnet-034ae4696445bb08b", # cht-platform-private-us-east-1a
  "subnet-0726a87cd7adfc9b2", # cht-platform-private-us-east-1b
]
public_subnet_ids = [
  "subnet-097bc6fcf27cf8c2b", # cht-platform-public-us-east-1a
  "subnet-0336bb6478c322091", # cht-platform-public-us-east-1b
]

cht_backend_security_group_id = "sg-0ca8dc900667da1bc"
cht_nat_gateway_cidr_blocks = [
  "54.83.140.14/32",
  "44.205.165.192/32",
]
alb_allow_public_ingress      = true
enable_waf                    = true

# Infra-first prod: Route53, ALB, RDS, ECS cluster + task def — API service deployed locally.
deploy_api_ecs_service = false

# Producer prod database — Aurora Global (matches CHT platform pattern).
enable_aurora_global  = true
aurora_instance_class = "db.r6g.large"
aurora_engine_version = "15.17"
aurora_use_for_app    = true
decommission_rds      = true

# Set on local API deploy (./scripts/deploy-api-service.sh prod)
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

cht_cache_clear_url = "https://testapp.communityhealth.media/api/internal/cache/catalog/clear"
