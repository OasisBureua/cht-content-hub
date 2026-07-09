#!/usr/bin/env bash
# Merge AWS Secrets Manager app-secrets JSON into local dev.tfvars / prod.tfvars.
# Run before terraform apply so platform keys are not wiped to empty strings.
#
# Usage:
#   ./scripts/sync-tfvars-secrets-from-sm.sh dev
#   ./scripts/sync-tfvars-secrets-from-sm.sh prod
set -euo pipefail

ENV="${1:-dev}"
REGION="${AWS_REGION:-us-east-1}"

case "$ENV" in
  dev) SM_NAME="contenthub-dev-app-secrets" ;;
  prod) SM_NAME="contenthub-prod-app-secrets" ;;
  *)
    echo "Usage: $0 [dev|prod]"
    exit 1
    ;;
esac

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TFVARS="$SCRIPT_DIR/../infrastructure/terraform/environments/variables/${ENV}.tfvars"

if [ ! -f "$TFVARS" ]; then
  echo "Missing $TFVARS — copy from ${ENV}.tfvars.example first"
  exit 1
fi

SECRET_FILE="$(mktemp)"
trap 'rm -f "$SECRET_FILE"' EXIT

aws secretsmanager get-secret-value \
  --secret-id "$SM_NAME" \
  --region "$REGION" \
  --query SecretString \
  --output text > "$SECRET_FILE"

python3 - "$TFVARS" "$ENV" "$SM_NAME" "$SECRET_FILE" << 'PY'
import json, pathlib, re, sys

tfvars_path = pathlib.Path(sys.argv[1])
env = sys.argv[2]
sm_name = sys.argv[3]
secret_file = pathlib.Path(sys.argv[4])
secrets = json.loads(secret_file.read_text())

text = tfvars_path.read_text()
text = re.sub(r"\n# ── Secrets.*", "", text, flags=re.DOTALL).rstrip() + "\n"

lines = [
    "",
    f"# ── Secrets (gitignored — synced from AWS SM {sm_name}) ─────────────",
    f"# Re-run: ./scripts/sync-tfvars-secrets-from-sm.sh {env}",
    "",
]
for key in sorted(secrets):
    val = secrets[key]
    if val is None:
        val = ""
    lines.append(f"{key} = {json.dumps(str(val))}")
lines.append("")

tfvars_path.write_text(text + "\n".join(lines) + "\n")
print(f"Updated {tfvars_path} with {len(secrets)} keys from {sm_name}")
PY
