#!/usr/bin/env bash
# Generate one company's tag-only OIDC publisher. Dry-run by default; never builds or releases.
# --apply performs IAM writes. AWS credentials come from the normal AWS credential chain.
set -euo pipefail
SCRIPT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="$SCRIPT_ROOT/..${PYTHONPATH:+:$PYTHONPATH}"
exec python3 "$SCRIPT_ROOT/company_app_publisher.py" "$@"
