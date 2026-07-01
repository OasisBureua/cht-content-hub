#!/usr/bin/env bash
# migrate-kol-headshots.sh — copy KOL PNGs from MediaHub EC2 → Content Hub S3 + rewrite photo_url
#
# Prerequisites:
#   - Terraform applied (s3_assets module)
#   - AWS CLI, SSM access to MediaHub EC2
#
# Usage:
#   ./scripts/migrate-kol-headshots.sh dev
#   ./scripts/migrate-kol-headshots.sh dev --skip-upload
#   ./scripts/migrate-kol-headshots.sh dev --skip-sql

set -euo pipefail

ENV="${1:-dev}"
SKIP_UPLOAD=false
SKIP_SQL=false
for arg in "${@:2}"; do
  case "$arg" in
    --skip-upload) SKIP_UPLOAD=true ;;
    --skip-sql) SKIP_SQL=true ;;
    *) echo "Unknown option: $arg"; exit 1 ;;
  esac
done

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TF_DIR="$ROOT/infrastructure/terraform/environments/us-east-1"
BACKEND_CONFIG="$ROOT/infrastructure/terraform/environments/backends/us-east-1-${ENV}.hcl"
EC2_INSTANCE_ID="${MEDIAHUB_EC2_INSTANCE_ID:-i-030c261389effc3d0}"
STAGING_PREFIX="contenthub-migration/kol-headshots"
STAGING_BUCKET="${MEDIAHUB_BACKUP_BUCKET:-chm-mediahub-backups}"
EC2_HEADSHOTS_DIR="${EC2_HEADSHOTS_DIR:-/home/ubuntu/chm_mediahub_assets/kol-headshots}"
REGION="${AWS_REGION:-us-east-1}"

cd "$TF_DIR"
terraform init -reconfigure -backend-config="$BACKEND_CONFIG" >/dev/null

ASSETS_BUCKET="$(terraform output -raw assets_bucket_name)"
HEADSHOTS_BASE="$(terraform output -raw kol_headshots_base_url)"
SECRET_ARN="$(terraform output -raw database_secret_arn)"
DB_HOST="$(aws secretsmanager get-secret-value --secret-id "$SECRET_ARN" --region "$REGION" --query SecretString --output text | python3 -c 'import sys,json; print(json.load(sys.stdin)["host"])')"

echo "→ Assets bucket:  s3://${ASSETS_BUCKET}/kol-headshots/"
echo "→ photo_url base: ${HEADSHOTS_BASE}/"
echo ""

if [ "$SKIP_UPLOAD" = false ]; then
  echo "=== Step 1: EC2 → staging S3 ==="
  CMD_ID="$(aws ssm send-command \
    --instance-ids "$EC2_INSTANCE_ID" \
    --document-name AWS-RunShellScript \
    --parameters "commands=[\"aws s3 sync ${EC2_HEADSHOTS_DIR} s3://${STAGING_BUCKET}/${STAGING_PREFIX}/ --delete\",\"aws s3 ls s3://${STAGING_BUCKET}/${STAGING_PREFIX}/ | wc -l\"]" \
    --region "$REGION" \
    --query Command.CommandId --output text)"
  echo "SSM command: $CMD_ID (waiting...)"
  STATUS="Pending"
  for _ in $(seq 1 30); do
    STATUS="$(aws ssm get-command-invocation --command-id "$CMD_ID" --instance-id "$EC2_INSTANCE_ID" --region "$REGION" --query Status --output text 2>/dev/null || echo Pending)"
    if [ "$STATUS" = "Success" ] || [ "$STATUS" = "Failed" ]; then
      break
    fi
    sleep 5
  done
  aws ssm get-command-invocation --command-id "$CMD_ID" --instance-id "$EC2_INSTANCE_ID" --region "$REGION" \
    --query '{Status:Status,Stdout:StandardOutputContent,Stderr:StandardErrorContent}' --output json
  if [ "$STATUS" != "Success" ]; then
    echo "✗ EC2 upload failed"
    exit 1
  fi

  echo ""
  echo "=== Step 2: staging → Content Hub assets bucket ==="
  aws s3 sync "s3://${STAGING_BUCKET}/${STAGING_PREFIX}/" "s3://${ASSETS_BUCKET}/kol-headshots/" --region "$REGION"
  COUNT="$(aws s3 ls "s3://${ASSETS_BUCKET}/kol-headshots/" --region "$REGION" | wc -l | tr -d ' ')"
  echo "✓ ${COUNT} objects in s3://${ASSETS_BUCKET}/kol-headshots/"
  echo ""
fi

if [ "$SKIP_SQL" = false ]; then
  echo "=== Step 3: rewrite kols.photo_url in RDS ==="
  export HEADSHOTS_BASE DB_HOST SECRET_ARN REGION
  python3 <<'PY'
import json, os, subprocess, time

region = os.environ["REGION"]
cluster = "contenthub-dev-cluster"
subnets = ["subnet-0a9d1329fbf64dbfb", "subnet-02ec72146e3abf115"]
sg = "sg-0b448831218790ada"
db_host = os.environ["DB_HOST"]
secret_arn = os.environ["SECRET_ARN"]
base = os.environ["HEADSHOTS_BASE"].replace("'", "''")

sql = f"""
UPDATE kols
SET photo_url = '{base}/' || substring(photo_url from '([^/]+)$')
WHERE photo_url IS NOT NULL
  AND photo_url LIKE '%kol-headshots/%';

SELECT count(*) FILTER (WHERE photo_url LIKE '{base}/%') AS on_contenthub_s3,
       count(*) FILTER (WHERE photo_url IS NOT NULL) AS with_photo
FROM kols;
"""

shell = f"""set -e
export PGPASSWORD="$PGPASSWORD"
psql -h {db_host} -U contenthub_admin -d contenthub_producer -v ON_ERROR_STOP=1 <<'EOSQL'
{sql}
EOSQL
"""

task_def = {
    "family": "contenthub-dev-pg-restore-oneoff",
    "networkMode": "awsvpc",
    "requiresCompatibilities": ["FARGATE"],
    "cpu": "256",
    "memory": "512",
    "executionRoleArn": "arn:aws:iam::233636046512:role/contenthub-dev-ecs-execution",
    "taskRoleArn": "arn:aws:iam::233636046512:role/contenthub-dev-ecs-task",
    "containerDefinitions": [{
        "name": "pg-restore",
        "image": "postgres:16-alpine",
        "essential": True,
        "command": ["sh", "-c", shell],
        "secrets": [{"name": "PGPASSWORD", "valueFrom": f"{secret_arn}:password::"}],
        "logConfiguration": {"logDriver": "awslogs", "options": {"awslogs-group": "/ecs/contenthub-dev", "awslogs-region": region, "awslogs-stream-prefix": "pg-restore"}},
    }],
}
path = "/tmp/headshots-sql.json"
with open(path, "w") as f:
    json.dump(task_def, f)
rev = json.loads(subprocess.check_output([
    "aws", "ecs", "register-task-definition",
    "--cli-input-json", f"file://{path}", "--region", region,
], text=True))["taskDefinition"]["revision"]
run = json.loads(subprocess.check_output([
    "aws", "ecs", "run-task",
    "--cluster", cluster,
    "--task-definition", f"contenthub-dev-pg-restore-oneoff:{rev}",
    "--launch-type", "FARGATE",
    "--network-configuration", json.dumps({"awsvpcConfiguration": {"subnets": subnets, "securityGroups": [sg], "assignPublicIp": "DISABLED"}}),
    "--region", region,
], text=True))
task_id = run["tasks"][0]["taskArn"].split("/")[-1]
print(f"ECS task {task_id}")
for _ in range(24):
    desc = json.loads(subprocess.check_output([
        "aws", "ecs", "describe-tasks", "--cluster", cluster,
        "--tasks", run["tasks"][0]["taskArn"], "--region", region,
    ], text=True))["tasks"][0]
    if desc["lastStatus"] == "STOPPED":
        print("exit", desc["containers"][0].get("exitCode"))
        break
    time.sleep(8)
events = json.loads(subprocess.check_output([
    "aws", "logs", "get-log-events",
    "--log-group-name", "/ecs/contenthub-dev",
    "--log-stream-name", f"pg-restore/pg-restore/{task_id}",
    "--limit", "20", "--region", region,
], text=True)).get("events", [])
for e in events:
    print(e["message"])
PY
fi

echo ""
echo "✓ Done. Verify:"
echo "  curl -sI \"${HEADSHOTS_BASE}/aditya-bardia.png\" | head -3"
