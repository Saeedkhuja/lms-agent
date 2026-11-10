#!/bin/bash
set -e

PORT=${PORT:-8000}
echo "=========================================================="
echo "🚀 e-JDU LMS Master Service (Render.com) ishga tushirilmoqda..."
echo "🌐 Port: $PORT"
echo "=========================================================="

if [ -n "$RENDER_EXTERNAL_URL" ]; then
    echo "🔗 Render URL: $RENDER_EXTERNAL_URL"
fi

# FastAPI o'zi startup eventida Telegram Botni avtomatik ishga tushiradi
echo "🎛️ FastAPI Master Dashboard va Telegram Bot ishga tushirilmoqda..."
exec uvicorn app:app --host 0.0.0.0 --port $PORT
