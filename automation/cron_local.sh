#!/usr/bin/env bash
# Self-hosted alternative to the GitHub Actions workflow.
#
# Add to crontab with:   crontab -e
# Then paste:
#
#     0 6 * * *  /path/to/pulpo.club/automation/cron_local.sh >> /var/log/pulpo.log 2>&1
#
# Every night at 06:00 SV time (UTC-6). Adjust path. Uses the repo's own venv.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

# Activate venv if it exists (created with `python3 -m venv .venv`)
if [ -d .venv ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

export PULPO_OFFLINE="${PULPO_OFFLINE:-0}"
export PULPO_LIMIT="${PULPO_LIMIT:-1000}"
# kazu: API host still denylisted. Re-add when rewritten as a JSON consumer.
export PULPO_SOURCES="${PULPO_SOURCES:-goodlife,oceanside,century21,bienesraices,remax}"

python3 automation/run.py

# If you push the dashboard to a static host (Vercel/Netlify/Cloudflare Pages),
# trigger a deploy here. Examples:
#   vercel --prod --yes --token "$VERCEL_TOKEN"
#   npx netlify deploy --prod --dir web
