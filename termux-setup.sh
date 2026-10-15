#!/data/data/com.termux/files/usr/bin/bash
# Lite one-time setup for Kuber Android. Minimal packages, minimal data.
set -e
export PYTHONDONTWRITEBYTECODE=1
pkg update -y
# python + termux-api only. grep/monkey are already on Android, no need to install.
pkg install -y python termux-api
pip install --no-cache-dir -r "$(dirname "$0")/requirements-android.txt"
termux-setup-storage || true
mkdir -p "$(dirname "$0")/workspace/downloads"
# Persist lite defaults (no .pyc, small history, no GPS by default)
grep -q PYTHONDONTWRITEBYTECODE ~/.bashrc 2>/dev/null || echo 'export PYTHONDONTWRITEBYTECODE=1' >> ~/.bashrc
grep -q KUBER_MAX_STEPS ~/.bashrc 2>/dev/null || echo 'export KUBER_MAX_STEPS=12' >> ~/.bashrc
grep -q KUBER_MAX_MB ~/.bashrc 2>/dev/null || echo 'export KUBER_MAX_MB=50' >> ~/.bashrc
echo ""
echo "Done. Next:"
echo "  1. export CF_ACCOUNT_ID=... CF_API_TOKEN=...   (same values as PC cf-setup)"
echo "  2. python my_agent_android.py --cloudflare"
echo "Tip: use the 8B model (default) to save Cloudflare neurons and data."
