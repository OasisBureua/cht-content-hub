#!/usr/bin/env bash
set -euo pipefail

ENVIRONMENT="${1:-us-east-1}"
ACTION="${2:-plan}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TF_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "MediaHub Terraform Deployment"
echo "Environment: $ENVIRONMENT"
echo "Action: $ACTION"
echo ""

cd "${TF_ROOT}/environments/${ENVIRONMENT}"

VAR_FILE="../variables/${ENVIRONMENT}.tfvars"
TF_VAR_ARGS=()
if [[ -f "$VAR_FILE" ]]; then
  TF_VAR_ARGS=(-var-file="${VAR_FILE}")
  echo "Using var file: ${VAR_FILE}"
elif [[ -f "../variables/dev.tfvars" ]]; then
  TF_VAR_ARGS=(-var-file="../variables/dev.tfvars")
  echo "Using var file: ../variables/dev.tfvars"
else
  echo "No tfvars found — set ../variables/dev.tfvars or ../variables/${ENVIRONMENT}.tfvars"
fi
echo ""

case "$ACTION" in
  init)
    terraform init
    ;;
  plan)
    terraform plan "${TF_VAR_ARGS[@]}"
    ;;
  apply)
    terraform apply "${TF_VAR_ARGS[@]}"
    ;;
  destroy)
    read -r -p "Destroy all MediaHub resources in ${ENVIRONMENT}? (yes/no): " confirm
    if [[ "$confirm" == "yes" ]]; then
      terraform destroy "${TF_VAR_ARGS[@]}"
    else
      echo "Aborted."
    fi
    ;;
  *)
    echo "Unknown action: $ACTION"
    echo "Usage: ./deploy.sh [us-east-1|us-east-2] [init|plan|apply|destroy]"
    exit 1
    ;;
esac

echo "Done."
