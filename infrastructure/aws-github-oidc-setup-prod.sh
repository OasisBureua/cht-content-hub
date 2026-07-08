#!/bin/bash
# Production OIDC setup — same as aws-github-oidc-setup.sh with stricter repo branch refs.
# Extend trust policy Condition to limit sub: repo:ORG/cht-content-hub:ref:refs/heads/main

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${SCRIPT_DIR}/aws-github-oidc-setup.sh"
