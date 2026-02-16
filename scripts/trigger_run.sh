#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${1:-http://127.0.0.1:8000}"
curl -s -X POST "$BASE_URL/api/runs/trigger" | sed -n '1,120p'
