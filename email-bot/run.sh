#!/bin/bash
# Called by cron every minute. Loads secrets and runs the bot.
BOT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$BOT_DIR/.env"

if [ ! -f "$ENV_FILE" ]; then
    echo "ERROR: $ENV_FILE not found. Run setup-vps.sh first." >&2
    exit 1
fi

# Load secrets
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

exec "$BOT_DIR/venv/bin/python" "$BOT_DIR/bot.py"
