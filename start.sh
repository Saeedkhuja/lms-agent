#!/usr/bin/env bash
# ==============================================================================
# e-JDU LMS Autonomous AI Agent Dashboard - Ishga tushirish skripti
# ==============================================================================

set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

echo "=========================================================="
echo "🤖 e-JDU LMS Autonomous AI Agent Dashboard ishga tushirilmoqda..."
echo "=========================================================="

# 1. Virtual Environment tekshirish / yaratish
if [ -d "../venv" ]; then
    echo "📦 ../venv muhiti aniqlandi va faollashtirilmoqda..."
    source ../venv/bin/activate
elif [ -d "venv" ]; then
    echo "📦 venv muhiti aniqlandi va faollashtirilmoqda..."
    source venv/bin/activate
else
    echo "⚙️ Yangi virtual environment (venv) yaratilmoqda..."
    python3 -m venv venv
    source venv/bin/activate
    echo "📥 Kutubxonalar o'rnatilmoqda..."
    pip install --upgrade pip
    pip install -r requirements.txt
    playwright install chromium
fi

# 2. Portni tekshirish va serverni ishga tushirish
PORT="${PORT:-8000}"
HOST="${HOST:-0.0.0.0}"

echo "🚀 Veb Dashboard quyidagi manzilda ishga tushmoqda:"
echo "👉 Local: http://localhost:${PORT}"
echo "👉 Tarmoq: http://${HOST}:${PORT}"
echo "=========================================================="

python3 -m uvicorn app:app --host "$HOST" --port "$PORT"
