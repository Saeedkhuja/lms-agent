#!/usr/bin/env bash
# Agentni orqa fonda (background) terminalsiz ishga tushirish
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

# Eski jarayon bo'lsa to'xtatish
pkill -f "uvicorn app:app" 2>/dev/null || true
sleep 1

nohup ./start.sh > app.log 2>&1 &
PID=$!

echo "=========================================================="
echo "✅ e-JDU AI Agent orqa fonda muvaffaqiyatli ishga tushirildi!"
echo "🆔 Jarayon PID: $PID"
echo "🌐 Veb Dashboard: http://localhost:8000"
echo "📜 Loglarni ko'rish: tail -f app.log"
echo "🛑 To'xtatish uchun: ./stop_background.sh"
echo "=========================================================="
