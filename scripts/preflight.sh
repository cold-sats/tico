#!/usr/bin/env bash
# Readiness check before flipping an employee from planned to active in registry/employees.yaml.
# Usage: scripts/preflight.sh <employee-slug> [<slug> ...] | scripts/preflight.sh --all
exec python3 "$(dirname "$0")/../clients/preflight.py" "$@"
