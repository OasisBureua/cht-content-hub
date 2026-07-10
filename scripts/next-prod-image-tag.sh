#!/usr/bin/env bash
# Backward-compatible wrapper — prefer scripts/next-ecr-image-tag.sh
exec "$(cd "$(dirname "$0")" && pwd)/next-ecr-image-tag.sh" "$@"
