#!/usr/bin/env bash
# Shared Terraform var-file resolution for Content Hub deploy scripts.
#
# Contract:
#   *.github.tfvars — committed non-secret infra (CI + local baseline)
#   *.tfvars        — gitignored secrets + optional local overrides (wins on conflict)
#
# Usage (from another script):
#   REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
#   # shellcheck source=scripts/terraform-var-files.sh
#   source "$REPO_ROOT/scripts/terraform-var-files.sh"
#   terraform_var_files_init prod
#   terraform plan "${TF_VAR_FILE_ARGS[@]}" ...
#
# After init:
#   TF_VAR_FILE_ARGS   — array: -var-file=github, then -var-file=local if present
#   TF_GITHUB_VAR_FILE — absolute path to *.github.tfvars
#   TF_LOCAL_VAR_FILE  — absolute path to *.tfvars (may not exist)

terraform_var_files_init() {
  local env="${1:?env required (dev|prod)}"
  case "$env" in
    dev|prod) ;;
    *)
      echo "terraform_var_files_init: unknown env '$env' (use dev or prod)" >&2
      return 1
      ;;
  esac

  local root="${REPO_ROOT:-}"
  if [ -z "$root" ]; then
    echo "terraform_var_files_init: set REPO_ROOT before sourcing" >&2
    return 1
  fi

  local vars_dir="$root/infrastructure/terraform/environments/variables"
  TF_GITHUB_VAR_FILE="$vars_dir/${env}.github.tfvars"
  TF_LOCAL_VAR_FILE="$vars_dir/${env}.tfvars"
  TF_VAR_FILE_ARGS=()

  if [ ! -f "$TF_GITHUB_VAR_FILE" ]; then
    echo "Missing $TF_GITHUB_VAR_FILE" >&2
    return 1
  fi

  TF_VAR_FILE_ARGS=(-var-file="$TF_GITHUB_VAR_FILE")
  if [ -f "$TF_LOCAL_VAR_FILE" ]; then
    TF_VAR_FILE_ARGS+=(-var-file="$TF_LOCAL_VAR_FILE")
  fi
}

# Read a tfvars key; local overrides github.
read_tfvar() {
  local key="${1:?}"
  local file value
  for file in "${TF_LOCAL_VAR_FILE:-}" "${TF_GITHUB_VAR_FILE:-}"; do
    [ -n "$file" ] && [ -f "$file" ] || continue
    value="$(grep -E "^${key}[[:space:]]*=" "$file" 2>/dev/null | head -1 | sed -E 's/^[^"]*"([^"]*)".*/\1/' || true)"
    if [ -n "$value" ]; then
      echo "$value"
      return 0
    fi
  done
  return 1
}

# Relative -var-file paths when cwd is infrastructure/terraform/environments/{us-east-1,us-east-2}.
terraform_var_files_relative_args() {
  local env="${1:?}"
  TF_VAR_FILE_REL_ARGS=(-var-file="../variables/${env}.github.tfvars")
  if [ -f "${REPO_ROOT}/infrastructure/terraform/environments/variables/${env}.tfvars" ]; then
    TF_VAR_FILE_REL_ARGS+=(-var-file="../variables/${env}.tfvars")
  fi
}
