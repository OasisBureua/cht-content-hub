# Content Hub — prod.github.tfvars
# Non-secret infra for GitHub Actions deploy-prod.yml (committed).
# Secrets: GitHub Environment "production" → TF_VAR_* (see .github/CI_CD.md).

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
alb_allow_public_ingress = true
enable_waf               = true

# ECS API service created/updated by deploy-prod.yml (Terraform apply each release).
deploy_api_ecs_service = true

# Producer prod database — Aurora Global (matches CHT platform pattern).
enable_aurora_global  = true
aurora_instance_class = "db.r6g.large"
aurora_engine_version = "15.17"
aurora_use_for_app    = true
decommission_rds      = true

# Replicate contenthub-api images us-east-1 → us-east-2 for DR ECS.
enable_ecr_replication             = true
ecr_replication_destination_region = "us-east-2"

# Secrets Manager multi-region replicas (CHT pattern).
secrets_replica_regions = ["us-east-2"]

# Overridden per deploy by workflow (-var api_image / dr_api_image).
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
  wordpress_ingest       = true
  # One-shot seed/backfill jobs. Prod was seeded during 2026-07-12 release
  # (1ffdd81 chore(prod): enable wordpress_ingest + this release). Handlers
  # are idempotent (skip existing rows) but keeping them enabled is
  # ambiguous about intent — flip to false post-seed. Re-enable temporarily
  # if a one-off restore is ever needed.
  clips_seed             = false
  wordpress_backfill     = false
  wordpress_seed         = false
}

# WordPress webhook ingress — dev only (see dev.github.tfvars). Empty on prod.
wordpress_ingress_cidr_blocks = []

cht_cache_clear_url = "https://testapp.communityhealth.media/api/internal/cache/clear/all"

# ── DR (us-east-2) — applied by deploy-prod.yml after use1 ───────────────────
dr_vpc_id = "vpc-0fbc2514f4e3467f2"
dr_private_subnet_ids = [
  "subnet-0b464add49b5eb6a3", # us-east-2a private (CHT platform DR VPC)
  "subnet-0923daa636b7f6acc", # us-east-2b private
]
dr_public_subnet_ids = [
  "subnet-0556f556073432a5f", # us-east-2a public
  "subnet-0b678003e2e3ec867", # us-east-2b public
]
dr_cht_backend_security_group_id = "sg-031ae76af7fd231f0"
dr_cht_nat_gateway_cidr_blocks = [
  "18.225.73.23/32",
  "3.151.76.8/32",
]
dr_acm_certificate_arn     = "arn:aws:acm:us-east-2:233636046512:certificate/e29d0bb5-022a-483c-ba4e-e97a5cc7a2e3"
dr_alb_allow_public_ingress  = true
dr_enable_waf              = true
dr_manage_route53          = true
dr_standby_scale_factor    = 0.5
dr_deploy_api_ecs_service  = true
dr_api_image               = "233636046512.dkr.ecr.us-east-2.amazonaws.com/contenthub-api:prod-latest"

# Route53 failover: keep false until ECS healthy in both regions; arm via ./scripts/arm-route53-failover.sh
enable_route53_failover = false
