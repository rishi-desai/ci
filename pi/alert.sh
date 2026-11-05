#!/usr/bin/env bash
# OnFailure hook for ci-gated-update@<app>: POST a text/plain message to ALERT_URL (ops.env).
# Without ALERT_URL the failure is only in the journal, which is logged, not treated as an error.
set -euo pipefail
app="${1:-unknown app}"
message="Deploy of $app failed on $(hostname). Inspect: journalctl -u ci-gated-update@$app -n 50"
echo "$message"
if [[ -z "${ALERT_URL:-}" ]]; then
  echo "ALERT_URL is not set in /etc/ci-gated-update/ops.env; failure recorded in the journal only"
  exit 0
fi
# Don't echo the URL or curl's URL-bearing errors: alert URLs often carry a token.
curl -fsS --max-time 10 --retry 2 --output /dev/null \
  --header 'Content-Type: text/plain' --data-binary "$message" "$ALERT_URL" 2>/dev/null \
  || { echo "failure webhook delivery failed"; exit 1; }
