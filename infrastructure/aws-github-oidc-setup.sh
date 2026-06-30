#!/bin/bash
set -e

echo "Setting up GitHub Actions OIDC for MediaHub AWS deploy"
echo "======================================================"
echo ""

read -p "GitHub org or user: " GITHUB_USER
read -p "Repository name [chm-mediahub]: " REPO_NAME
REPO_NAME=${REPO_NAME:-chm-mediahub}

AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cat > /tmp/github-trust-policy.json << TRUST
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
          "token.actions.githubusercontent.com:sub": "repo:${GITHUB_USER}/${REPO_NAME}:*"
        }
      }
    }
  ]
}
TRUST

aws iam create-open-id-connect-provider \
  --url https://token.actions.githubusercontent.com \
  --client-id-list sts.amazonaws.com \
  --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1 \
  2>/dev/null || echo "OIDC provider already exists"

ROLE_NAME="GitHubActions-MediaHub"
ROLE_ARN=$(aws iam create-role \
  --role-name "$ROLE_NAME" \
  --assume-role-policy-document file:///tmp/github-trust-policy.json \
  --query 'Role.Arn' \
  --output text 2>/dev/null || \
  aws iam get-role --role-name "$ROLE_NAME" --query 'Role.Arn' --output text)

POLICY_NAME="GitHubActions-MediaHub-Deploy"
POLICY_DOC="${SCRIPT_DIR}/iam/github-actions-deploy-policy.json"
sed "s/ACCOUNT_ID/${AWS_ACCOUNT_ID}/g" "$POLICY_DOC" > /tmp/mediahub-deploy-policy.json

POLICY_ARN=$(aws iam create-policy \
  --policy-name "$POLICY_NAME" \
  --policy-document file:///tmp/mediahub-deploy-policy.json \
  --query 'Policy.Arn' \
  --output text 2>/dev/null || \
  aws iam get-policy --policy-arn "arn:aws:iam::${AWS_ACCOUNT_ID}:policy/${POLICY_NAME}" --query 'Policy.Arn' --output text)

aws iam attach-role-policy --role-name "$ROLE_NAME" --policy-arn "$POLICY_ARN"

echo ""
echo "Done. Add to GitHub repository secrets:"
echo "AWS_ROLE_ARN=$ROLE_ARN"
echo ""

rm -f /tmp/github-trust-policy.json /tmp/mediahub-deploy-policy.json
