#!/bin/bash
set -e

PORT=${PORT:-8000}
echo "=========================================================="
echo "🚀 e-JDU LMS Master Service (Render.com) ishga tushirilmoqda..."
echo "🌐 Port: $PORT"
echo "=========================================================="

# Agar RENDER_EXTERNAL_URL mavjud bo'lsa, xabar chiqarish
if [ -n "$RENDER_EXTERNAL_URL" ]; then
    echo "🔗 Render URL: $RENDER_EXTERNAL_URL"
fi

# 1. Telegram Botni fonda ishga tushirish
echo "🤖 Telegram Bot fon rejimida yoqilmoqda..."
python3 telegram_bot.py &
BOT_PID=$!
echo "✅ Telegram Bot ishga tushdi (PID: $BOT_PID)"

# 2. FastAPI Master Dashboardni asosiy jarayon sifatida ishga tushirish
echo "🎛️ FastAPI Master Dashboard ishga tushirilmoqda..."
exec uvicorn app:app --host 0.0.0.0 --port $PORT
