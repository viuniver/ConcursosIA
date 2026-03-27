#!/usr/bin/env bash
# Script para execução diária via cron ou manualmente.
# Uso: ./run_daily.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$SCRIPT_DIR/logs"
LOG_FILE="$LOG_DIR/coleta_$(date +%Y%m%d).log"

mkdir -p "$LOG_DIR"

cd "$SCRIPT_DIR"

# Ativa virtualenv se existir
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
fi

echo "$(date '+%Y-%m-%d %H:%M:%S') — Iniciando coleta ConcursosIA" | tee -a "$LOG_FILE"

python -m app.main run 2>&1 | tee -a "$LOG_FILE"

echo "$(date '+%Y-%m-%d %H:%M:%S') — Coleta finalizada" | tee -a "$LOG_FILE"
