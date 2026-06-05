#!/usr/bin/env bash
# Trigger ONE scan via the local API. Sends the X-Scan-Token header ONLY when SCAN_TOKEN is set
# (PR S3/S4) — an inline curl can't do that conditionally, which is why this wrapper exists. Fired by
# kalshi-dashboard-scan.timer; uses the same EnvironmentFile so it sees API_PORT + SCAN_TOKEN.
set -euo pipefail
URL="http://127.0.0.1:${API_PORT:-8000}/scan"
if [ -n "${SCAN_TOKEN:-}" ]; then
  curl -fsS -X POST -H "X-Scan-Token: ${SCAN_TOKEN}" "$URL"
else
  curl -fsS -X POST "$URL"
fi
