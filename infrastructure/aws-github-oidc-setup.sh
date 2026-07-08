#!/usr/bin/env bash
# One-time GitHub Actions OIDC setup for cht-content-hub deploys.
#
# Creates (or reuses):
#   - OIDC provider token.actions.githubusercontent.com (account-level)
#   - IAM role GitHubActions-ContentHub-Deploy
#   - IAM policy GitHubActions-ContentHub-Deploy
#
# Usage:
#   ./infrastructure/aws-github-oidc-setup.sh
#   GITHUB_USER=myorg REPO_NAME=cht-content-hub ./infrastructure/aws-github-oidc-setup.sh
#   GITHUB_ENVIRONMENT=development ./infrastructure/aws-github-oidc-setup.sh
#
# Then add AWS_ROLE_ARN to GitHub → Settings → Environments → development → Secrets
set -euo pipefail

echo "🔐 GitHub Actions OIDC — Content Hub (cht-content-hub)"
echo "======================================================="
echo ""

GITHUB_USER="${GITHUB_USER:-}"
REPO_NAME="${REPO_NAME:-cht-content-hub}"
GITHUB_ENVIRONMENT="${GITHUB_ENVIRONMENT:-development}"
ROLE_NAME="GitHubActions-ContentHub-Deploy"
POLICY_NAME="GitHubActions-ContentHub-Deploy"

if [ -z "$GITHUB_USER" ]; then
  read -r -p "GitHub org or username (e.g. communityhealth): " GITHUB_USER
fi

AWS_ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo ""
echo "📋 Configuration:"
echo "  AWS Account:  $AWS_ACCOUNT_ID"
echo "  GitHub repo:  ${GITHUB_USER}/${REPO_NAME}"
echo "  Environment:  ${GITHUB_ENVIRONMENT} (trust sub filter)"
echo "  IAM role:     ${ROLE_NAME}"
echo ""

TRUST_FILE="$(mktemp)"
trap 'rm -f "$TRUST_FILE"' EXIT

cat > "$TRUST_FILE" <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::${AWS_ACCOUNT_ID}:oidc-provider/token.actions.githubusercontent.com"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
        },
        "StringLike": {
          "token.actions.githubusercontent.com:sub": "repo:${GITHUB_USER}/${REPO_NAME}:environment:${GITHUB_ENVIRONMENT}"
        }
      }
    }
  ]
}
EOF

echo "🔧 OIDC provider (skip if already exists)..."
aws iam create-open-id-connect-provider \
  --url https://token.actions.githubusercontent.com \
  --client-id-list sts.amazonaws.com \
  --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1 \
  2>/dev/null || echo "  ✓ OIDC provider already exists"

echo "👤 IAM role ${ROLE_NAME}..."
if aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
  echo "  → Updating trust policy on existing role"
  aws iam update-assume-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-document "file://${TRUST_FILE}"
  ROLE_ARN="$(aws iam get-role --role-name "$ROLE_NAME" --query 'Role.Arn' --output text)"
else
  ROLE_ARN="$(aws iam create-role \
    --role-name "$ROLE_NAME" \
    --assume-role-policy-document "file://${TRUST_FILE}" \
    --description "GitHub Actions deploy role for cht-content-hub (${GITHUB_ENVIRONMENT})" \
    --query 'Role.Arn' \
    --output text)"
fi
echo "  ✓ ${ROLE_ARN}"

echo "📎 IAM policy ${POLICY_NAME}..."
POLICY_ARN="$(aws iam create-policy \
  --policy-name "$POLICY_NAME" \
  --policy-document "file://${SCRIPT_DIR}/iam/github-actions-deploy-policy.json" \
  --description "Scoped deploy policy for cht-content-hub GitHub Actions" \
  --query 'Policy.Arn' \
  --output text 2>/dev/null || \
  aws iam get-policy \
    --policy-arn "arn:aws:iam::${AWS_ACCOUNT_ID}:policy/${POLICY_NAME}" \
    --query 'Policy.Arn' --output text)"

# Publish new policy version when document changes (keep last 4 versions)
aws iam create-policy-version \
  --policy-arn "$POLICY_ARN" \
  --policy-document "file://${SCRIPT_DIR}/iam/github-actions-deploy-policy.json" \
  --set-as-default 2>/dev/null || true

aws iam attach-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-arn "$POLICY_ARN" 2>/dev/null || echo "  ✓ Policy already attached"

echo ""
echo "✅ Setup complete"
echo ""
echo "Add to GitHub → Settings → Environments → ${GITHUB_ENVIRONMENT} → Environment secrets:"
echo ""
echo "  AWS_ROLE_ARN=${ROLE_ARN}"
echo ""
echo "Also add (same values as local TF_VAR_*):"
echo "  PUBLIC_API_KEY"
echo "  WEBHOOK_API_KEY"
echo "  JWT_SECRET"
echo "  INTERNAL_CACHE_SECRET"
echo ""
echo "Verify:"
echo "  PUBLIC_API_KEY=... WEBHOOK_API_KEY=... JWT_SECRET=... INTERNAL_CACHE_SECRET=... \\"
echo "    AWS_ROLE_ARN=${ROLE_ARN} ./scripts/verify-github-env-secrets.sh ${GITHUB_ENVIRONMENT}"
echo ""
echo "First deploy: Actions → Deploy to Development → Run workflow"
echo "  Image tag will be 1.0.0 (then 1.0.1, ...) — see scripts/next-dev-image-tag.sh"
