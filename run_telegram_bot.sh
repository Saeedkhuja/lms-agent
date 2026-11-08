#!/usr/bin/env bash
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

if [ -f "../venv/bin/activate" ]; then
    source ../venv/bin/activate
elif [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
fi

pkill -f "telegram_bot.py" 2>/dev/null || true
sleep 1

nohup python3 telegram_bot.py > telegram_bot.log 2>&1 &
PID=$!

echo "=========================================================="
echo "🤖 LMS Telegram Bot orqa fonda ishga tushirildi!"
echo "🆔 Jarayon PID: $PID"
echo "📜 Loglarni ko'rish: tail -f telegram_bot.log"
echo "🛑 To'xtatish uchun: pkill -f telegram_bot.py"
echo "=========================================================="
