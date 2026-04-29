#!/usr/bin/env bash
# Self-hosted alternative to the GitHub Actions workflow.
#
# Add to crontab with:   crontab -e
# Then paste:
#
#     0 6 * * 3  /path/to/pulpo-sv/automation/cron_local.sh >> /var/log/pulpo.log 2>&1
#
# Wednesday 06:00 SV time. Adjust path. Uses the repo's own venv.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

# Activate venv if it exists (created with `python3 -m venv .venv`)
if [ -d .venv ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

# Use offline=0 once selectors are calibrated against the live sites
export PULPO_OFFLINE="${PULPO_OFFLINE:-0}"
export PULPO_LIMIT="${PULPO_LIMIT:-60}"
export PULPO_SOURCES="${PULPO_SOURCES:-goodlife,oceanside,kazu}"

python3 automation/run.py

# If you push the dashboard to a static host (Vercel/Netlify/Cloudflare Pages),
# trigger a deploy here. Examples:
#   vercel --prod --yes --token "$VERCEL_TOKEN"
#   npx netlify deploy --prod --dir web
