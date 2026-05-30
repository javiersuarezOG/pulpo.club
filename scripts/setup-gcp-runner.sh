#!/usr/bin/env bash
# Install + register a GitHub Actions self-hosted runner on a fresh
# GCP Debian/Ubuntu VM. The resulting runner is labelled
# `gcp-residential` and survives reboots via systemd.
#
# Why this exists
# ---------------
# realtyelsalvador + elagente's WAFs (Cloudflare) block GitHub-hosted
# runner IPs (Azure) AND Vercel/AWS Lambda IPs. Google Cloud IPs slip
# past — confirmed 2026-05-30 via probes from Cloud Shell and an /api
# endpoint deployed to Vercel (us-east-1). A self-hosted runner on a
# free-tier GCP e2-micro is the cheapest known path to a working IP
# range for those two scrapers.
#
# What this script does
# ---------------------
# 1. Validates the VM has the prereqs (curl, tar, systemd, write to /opt).
# 2. Downloads the latest GitHub Actions runner tarball for x64 Linux.
# 3. Configures it against the pulpo.club repo using the registration
#    token you pass in as $RUNNER_TOKEN. The token is single-use, 1h
#    expiry — fetch one fresh per install.
# 4. Tags the runner with the label `gcp-residential` so the workflow
#    can target it explicitly with `runs-on: gcp-residential`.
# 5. Installs the runner as a systemd service that auto-starts on boot.
#
# Prereqs (manual, one-time)
# --------------------------
#   - GCP project with billing enabled (free tier doesn't require a
#     paid card, but the project still has to exist).
#   - A VM: e2-micro on us-central1, us-west1, or us-east1 is free up
#     to 744 hr/mo (i.e. always-on for the whole month). Debian 12
#     image is the default; the script works on Debian/Ubuntu.
#   - Open the VM's SSH port (GCP console adds it by default).
#   - A registration token from
#     https://github.com/javiersuarezOG/pulpo.club/settings/actions/runners/new
#     Pick "Linux x64", scroll past the install steps, copy the token
#     from the `./config.sh --token XXXXX` line. It's a one-shot,
#     ~1h-valid token; only used to register the runner with GitHub.
#
# Usage
# -----
#   # On the GCP VM, after ssh-ing in:
#   sudo apt-get update && sudo apt-get install -y curl
#   curl -sLo setup-gcp-runner.sh \
#     https://raw.githubusercontent.com/javiersuarezOG/pulpo.club/main/scripts/setup-gcp-runner.sh
#   chmod +x setup-gcp-runner.sh
#   RUNNER_TOKEN=AABBCC... sudo -E ./setup-gcp-runner.sh
#
# Verification
# ------------
# After the script exits 0, visit
# https://github.com/javiersuarezOG/pulpo.club/settings/actions/runners
# — your runner should appear with status "Idle" and label
# `gcp-residential`. The first workflow that targets `runs-on:
# gcp-residential` will pick it up.
#
# Maintenance
# -----------
#   - The runner self-updates on each job. Manual upgrades are rarely
#     needed; if one is, re-run this script (it's idempotent against
#     the install path).
#   - Logs: `journalctl -u actions.runner.* -f` on the VM.
#   - To uninstall: `cd /opt/actions-runner && sudo ./svc.sh stop &&
#     sudo ./svc.sh uninstall && sudo ./config.sh remove --token <new>`.
#     Reuse a freshly-minted token for the remove call (yes, it's a
#     separate token from the install one — same URL, different
#     button).
#
# Cost guardrails
# ---------------
# An e2-micro in a free-tier region is $0/mo if it stays under the 744
# hour ceiling. Two side effects to watch:
#   - Egress > 1 GB/mo: $0.12/GB. Pulpo's scraper-shim downloads ~2 MB
#     of HTML per nightly, well under the limit.
#   - Persistent disk > 30 GB: paid. Stick to the default 30 GB or
#     smaller; the runner + repo clone fit in <5 GB.

set -euo pipefail

# ── 0. Sanity checks ──────────────────────────────────────────────────
if [ "$(id -u)" -ne 0 ]; then
  echo "ERROR: must run as root (use sudo -E)." >&2
  exit 1
fi
if [ -z "${RUNNER_TOKEN:-}" ]; then
  echo "ERROR: RUNNER_TOKEN env var is required." >&2
  echo "  Get one from: https://github.com/javiersuarezOG/pulpo.club/settings/actions/runners/new" >&2
  echo "  Then: RUNNER_TOKEN=AAA... sudo -E ./setup-gcp-runner.sh" >&2
  exit 1
fi

for bin in curl tar systemctl; do
  if ! command -v "$bin" >/dev/null 2>&1; then
    echo "ERROR: $bin not found. Install with: apt-get install -y $bin" >&2
    exit 1
  fi
done

# ── 1. Resolve the latest runner version + tarball URL ────────────────
# GitHub's API exposes "latest" without auth. The tarball name embeds
# the version (e.g. actions-runner-linux-x64-2.319.1.tar.gz). Pinning
# would also work — we go latest because the runner auto-updates per
# job anyway, so a fresh install at "latest" makes future re-runs
# converge cleanly.
RUNNER_ARCH="x64"
LATEST_JSON=$(curl -sf https://api.github.com/repos/actions/runner/releases/latest)
RUNNER_VERSION=$(echo "$LATEST_JSON" | grep -oE '"tag_name": "v[^"]+"' | head -1 | sed 's/.*"v\(.*\)"/\1/')
if [ -z "$RUNNER_VERSION" ]; then
  echo "ERROR: failed to resolve latest runner version from GitHub API." >&2
  exit 1
fi
TARBALL="actions-runner-linux-${RUNNER_ARCH}-${RUNNER_VERSION}.tar.gz"
DOWNLOAD_URL="https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/${TARBALL}"
echo "[setup] runner v${RUNNER_VERSION}"

# ── 2. Install location + user ───────────────────────────────────────
# Use a dedicated unprivileged user (`gh-runner`) — never run the
# runner as root. The runner executes arbitrary CI code; a least-
# privilege account keeps a misbehaving job from touching the rest of
# the VM.
INSTALL_DIR="/opt/actions-runner"
RUNNER_USER="gh-runner"

if ! id "$RUNNER_USER" >/dev/null 2>&1; then
  echo "[setup] creating user $RUNNER_USER"
  useradd --system --create-home --shell /bin/bash "$RUNNER_USER"
fi

mkdir -p "$INSTALL_DIR"
chown "$RUNNER_USER:$RUNNER_USER" "$INSTALL_DIR"

# ── 3. Download + extract the runner tarball ─────────────────────────
if [ ! -f "$INSTALL_DIR/config.sh" ]; then
  echo "[setup] downloading $TARBALL"
  TMP_TAR="/tmp/$TARBALL"
  curl -sfL -o "$TMP_TAR" "$DOWNLOAD_URL"
  sudo -u "$RUNNER_USER" tar -xzf "$TMP_TAR" -C "$INSTALL_DIR"
  rm -f "$TMP_TAR"
else
  echo "[setup] runner files already present in $INSTALL_DIR"
fi

# Install runner-deps (libssl etc.). The runner ships its own
# bootstrap script for these; safer than guessing.
if [ -x "$INSTALL_DIR/bin/installdependencies.sh" ]; then
  echo "[setup] installing runner OS dependencies"
  bash "$INSTALL_DIR/bin/installdependencies.sh"
fi

# ── 4. Python + scraper deps the shim needs ──────────────────────────
# The Phase-2 scrape shim runs `python3 -m <module>` and needs the
# same Pulpo runtime deps the main nightly uses. Install them here so
# the runner is self-sufficient by the time Phase 2 ships.
echo "[setup] installing Python + scraper deps"
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-venv git

# ── 5. Register the runner with GitHub ───────────────────────────────
# Always re-register, even on re-runs — tokens are single-use and the
# config script no-ops cleanly if the runner is already configured
# under the same name + URL.
echo "[setup] registering runner with GitHub"
HOSTNAME_SHORT=$(hostname -s)
sudo -u "$RUNNER_USER" "$INSTALL_DIR/config.sh" \
  --unattended \
  --url "https://github.com/javiersuarezOG/pulpo.club" \
  --token "$RUNNER_TOKEN" \
  --name "gcp-${HOSTNAME_SHORT}" \
  --labels "gcp-residential" \
  --work "_work" \
  --replace

# ── 6. Install as a systemd service so it survives reboots ───────────
echo "[setup] installing systemd unit"
cd "$INSTALL_DIR"
./svc.sh install "$RUNNER_USER"
./svc.sh start

echo
echo "[setup] DONE."
echo
echo "Verify at:"
echo "  https://github.com/javiersuarezOG/pulpo.club/settings/actions/runners"
echo "  Look for: 'gcp-${HOSTNAME_SHORT}' (Idle), label gcp-residential"
echo
echo "Tail runner logs:"
echo "  journalctl -u 'actions.runner.*' -f"
