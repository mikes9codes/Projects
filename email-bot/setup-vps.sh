#!/bin/bash
# One-time setup for the Redan bot on a Ubuntu VPS.
# Run as root: bash email-bot/setup-vps.sh
set -e

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BOT_DIR="$REPO_DIR/email-bot"

echo "=== Redan Email Bot — VPS Setup ==="
echo "Repo: $REPO_DIR"

# System packages
apt-get update -qq
apt-get install -y python3 python3-pip python3-venv git

# Python virtual environment
python3 -m venv "$BOT_DIR/venv"
"$BOT_DIR/venv/bin/pip" install -q --upgrade pip
"$BOT_DIR/venv/bin/pip" install -q -r "$BOT_DIR/requirements.txt"

# Playwright browser (headless Chromium + system deps)
"$BOT_DIR/venv/bin/playwright" install --with-deps chromium

chmod +x "$BOT_DIR/run.sh"
chmod +x "$BOT_DIR/install-cron.sh"

echo ""
echo "=== Next: create your secrets file ==="
echo "Run this (fill in real values):"
echo ""
echo "  cat > $BOT_DIR/.env << 'EOF'"
echo "  VERIZON_EMAIL=mikes9@verizon.net"
echo "  VERIZON_APP_PASSWORD=your_aol_app_password"
echo "  ANTHROPIC_API_KEY=your_anthropic_key"
echo "  EOF"
echo ""
echo "Then run:  bash $BOT_DIR/install-cron.sh"
