#!/usr/bin/env bash
# Prints the four compose.yaml settings that place the edge network on one /28, from its first three octets:
#   docker/edge-env.sh 172.30.253 >> .env
# The subnet, the range Docker hands out to other containers, and the two front doors' fixed addresses below it must
# move together. Each stack the release checks run side by side appends this for its own range, since Docker refuses
# a second network on a range already in use.
set -euo pipefail
prefix="${1:-}"
[[ "$prefix" =~ ^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$ ]] || { echo "usage: docker/edge-env.sh A.B.C (the /28 is A.B.C.0/28)" >&2; exit 2; }
printf 'TICO_EDGE_SUBNET=%s.0/28\nTICO_EDGE_DYNAMIC_RANGE=%s.8/29\nTICO_CADDY_ADDRESS=%s.2\nTICO_CLOUDFLARED_ADDRESS=%s.3\n' \
  "$prefix" "$prefix" "$prefix" "$prefix"
