#!/bin/bash
# Backup corpus.db with timestamp
# Usage: ./backup-corpus.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP_DIR="$SCRIPT_DIR/backups"
DB_PATH="$SCRIPT_DIR/corpus.db"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
BACKUP_PATH="$BACKUP_DIR/corpus-$TIMESTAMP.db"

# Create backup directory if needed
mkdir -p "$BACKUP_DIR"

# Check if database exists
if [ ! -f "$DB_PATH" ]; then
    echo "Error: corpus.db not found at $DB_PATH"
    exit 1
fi

# Create backup
cp "$DB_PATH" "$BACKUP_PATH"

# Get some stats
LABELS=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM labels" 2>/dev/null || echo "?")
NOISE=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM noise_predictions" 2>/dev/null || echo "?")
SIZE=$(du -h "$BACKUP_PATH" | cut -f1)

echo "Backed up corpus.db"
echo "  Location: $BACKUP_PATH"
echo "  Size: $SIZE"
echo "  Labels: $LABELS"
echo "  Noise predictions: $NOISE"

# Clean old backups (keep last 10)
cd "$BACKUP_DIR"
ls -t corpus-*.db 2>/dev/null | tail -n +11 | xargs -r rm -f
KEPT=$(ls corpus-*.db 2>/dev/null | wc -l | tr -d ' ')
echo "  Backups kept: $KEPT"
