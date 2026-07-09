# Content Hub — dev.github.tfvars
# Non-secret infra for GitHub Actions deploy-dev.yml (committed).
# Secrets: GitHub Environment "development" → TF_VAR_* (see .github/CI_CD.md).

project     = "contenthub"
environment = "dev"
deploy_mode = "cht-vpc"

api_domain          = "devhub.communityhealth.media"
acm_certificate_arn = "arn:aws:acm:us-east-1:233636046512:certificate/af1bbde1-73fe-4db2-99aa-dd64dc7f8a55"

vpc_id = "vpc-095c20b7e874013f2"
private_subnet_ids = [
  "subnet-02ec72146e3abf115",
  "subnet-0a9d1329fbf64dbfb",
]
public_subnet_ids = [
  "subnet-09f9a429f7da9da10",
  "subnet-07d53b4649e5432fc",
]

cht_backend_security_group_id = "sg-0363efdc457aa7341"
cht_nat_gateway_cidr_blocks = [
  "18.233.236.119/32",
  "44.223.243.240/32",
]
alb_allow_public_ingress = false
enable_waf             = true

# Overridden per deploy by workflow (-var api_image)
api_image = "233636046512.dkr.ecr.us-east-1.amazonaws.com/contenthub-dev-api:1.0.0"

rds_instance_class    = "db.t4g.small"
rds_engine_version    = "15.17"
rds_allocated_storage = 20
rds_multi_az          = false
rds_backup_retention  = 7
log_retention_days    = 7

api_task_cpu      = 512
api_task_memory   = 1024
api_desired_count = 1
api_min_capacity  = 1
api_max_capacity  = 4

worker_desired_count = 0

sync_jobs_enabled = {
  cache_clear            = false
  hcp_intel_poll         = false
  openalex_backfill      = false
  kol_hcp_matcher        = false
  post_tagging           = false
  playlist_doctor_tagger = false
}

# Platform integration secrets are NOT stored here (committed file).
# Add GitHub Environment "development" secrets → TF_VAR_* on deploy.
# See .github/CI_CD.md — e.g. LINKEDIN_ADS_CLIENT_ID, YOUTUBE_API_KEY, OPENAI_API_KEY.

cht_cache_clear_url = "https://devapp.communityhealth.media/api/internal/cache/catalog/clear"
