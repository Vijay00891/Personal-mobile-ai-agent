#!/data/data/com.termux/files/usr/bin/bash
# Run ONCE in Termux after copying the android folder to the phone.
set -e
pkg update -y
pkg install -y python termux-api grep monkey
pip install --upgrade pip
pip install -r "$(dirname "$0")/requirements-android.txt"
# Allow access to shared storage (accept the popup)
termux-setup-storage || true
mkdir -p "$(dirname "$0")/workspace/downloads"
echo ""
echo "Done. Next:"
echo "  1. export CF_ACCOUNT_ID=... CF_API_TOKEN=...   (same values as PC cf-setup)"
echo "  2. python my_agent_android.py --cloudflare"
