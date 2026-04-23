#!/bin/bash
# Installs the every-minute cron job and sets up log rotation.
SCRIPT="$(cd "$(dirname "$0")" && pwd)/run.sh"
LOG="$HOME/redan-bot.log"

chmod +x "$SCRIPT"

# Add to crontab (idempotent — removes any old entry first)
( crontab -l 2>/dev/null | grep -v "redan.*run.sh" ; \
  echo "* * * * * $SCRIPT >> $LOG 2>&1" ) | crontab -

echo "Cron job installed:"
crontab -l | grep run.sh

# Simple log rotation: keep last 500 lines on each run
ROTATE_ENTRY="*/30 * * * * tail -n 500 $LOG > ${LOG}.tmp && mv ${LOG}.tmp $LOG"
( crontab -l 2>/dev/null | grep -v "tail.*redan" ; \
  echo "$ROTATE_ENTRY" ) | crontab -

echo ""
echo "Done. Bot runs every minute. Logs: $LOG"
echo "Test now with: bash $SCRIPT"
