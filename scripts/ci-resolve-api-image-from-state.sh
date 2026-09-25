#!/usr/bin/env bash
# Resolve the currently applied API image from Terraform state.
# Used by CI when this run is not building a new image so terraform apply
# does not roll ECS back to the placeholder tag in *.github.tfvars.
#
# Usage (from TF env dir, after terraform init):
#   eval "$(../../../../scripts/ci-resolve-api-image-from-state.sh)"
#   # exports API_IMAGE
set -euo pipefail

if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required" >&2
  exit 1
fi

if ! command -v terraform >/dev/null 2>&1; then
  echo "terraform is required" >&2
  exit 1
fi

STATE_JSON="$(terraform show -json)"

API_IMAGE="$(
  echo "$STATE_JSON" | jq -r '
    [
      ..
      | objects
      | select(
          (.type? == "aws_ecs_task_definition")
          and ((.address? // .name? // "") | tostring | test("ecs_api|task_definition\\.api"))
        )
      | (.values.container_definitions // empty)
    ]
    | map(select(type == "string" and length > 0))
    | first
    | if . == null then empty else (fromjson | .[0].image) end
  '
)"

if [ -z "${API_IMAGE:-}" ]; then
  echo "Could not resolve current API image from Terraform state." >&2
  echo "Refusing a plan that would risk rolling ECS back to tfvars placeholders." >&2
  exit 1
fi

echo "Resolved current API image from state: ${API_IMAGE}" >&2
printf "API_IMAGE=%q\n" "$API_IMAGE"
