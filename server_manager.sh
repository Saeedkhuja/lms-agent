#!/usr/bin/env bash
# ==============================================================================
# e-JDU LMS Server & Bot Controller - 24/7 Production Daemon Manager
# ==============================================================================

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

ACTION="${1:-status}"

start_all() {
    echo "🚀 Barcha servislar ishga tushirilmoqda..."
    
    # 1. Start Web Dashboard
    pkill -f "uvicorn app:app" 2>/dev/null || true
    sleep 1
    nohup /home/saeed/Downloads/venv/bin/python3 -m uvicorn app:app --host 0.0.0.0 --port 8000 > /tmp/uvicorn.log 2>&1 &
    echo "✅ [1/3] Web Dashboard ishga tushirildi (Port: 8000)"
    
    # 2. Start Telegram Bot
    pkill -f "telegram_bot.py" 2>/dev/null || true
    sleep 1
    nohup /home/saeed/Downloads/venv/bin/python3 telegram_bot.py > /tmp/telegram_bot.log 2>&1 &
    echo "✅ [2/3] Telegram Bot ishga tushirildi (@vvccddkjvrcuccffccu_bot)"
    
    # 3. Start Cloudflare Tunnel
    pkill -f "cloudflared tunnel" 2>/dev/null || true
    sleep 1
    nohup /home/saeed/Downloads/cloudflared tunnel --url http://localhost:8000 > /tmp/cloudflared.log 2>&1 &
    echo "✅ [3/3] Cloudflare Tunnel ishga tushirildi"
    
    sleep 4
    URL=$(grep -o 'https://[-a-z0-9.]*\.trycloudflare\.com' /tmp/cloudflared.log | tail -n 1)
    echo "=========================================================="
    echo "🌐 Global HTTPS Manzil: $URL"
    echo "🤖 Telegram Bot: https://t.me/vvccddkjvrcuccffccu_bot"
    echo "=========================================================="
}

stop_all() {
    echo "🛑 Barcha servislar to'xtatilmoqda..."
    pkill -f "uvicorn app:app" 2>/dev/null || true
    pkill -f "telegram_bot.py" 2>/dev/null || true
    pkill -f "cloudflared tunnel" 2>/dev/null || true
    echo "✅ Barcha servislar to'xtatildi."
}

show_status() {
    echo "=========================================================="
    echo "📊 e-JDU LMS SERVISLAR HOLATI:"
    echo "=========================================================="
    
    if pgrep -f "uvicorn app:app" > /dev/null; then
        echo "🟢 Web Dashboard: ISHLAMOQDA (PID: $(pgrep -f 'uvicorn app:app' | head -n 1))"
    else
        echo "🔴 Web Dashboard: TO'XTATILGAN"
    fi
    
    if pgrep -f "telegram_bot.py" > /dev/null; then
        echo "🟢 Telegram Bot: ISHLAMOQDA (PID: $(pgrep -f 'telegram_bot.py' | head -n 1))"
    else
        echo "🔴 Telegram Bot: TO'XTATILGAN"
    fi
    
    if pgrep -f "cloudflared tunnel" > /dev/null; then
        URL=$(grep -o 'https://[-a-z0-9.]*\.trycloudflare\.com' /tmp/cloudflared.log 2>/dev/null | tail -n 1)
        echo "🟢 Cloudflare Tunnel: ISHLAMOQDA"
        [ -n "$URL" ] && echo "🔗 Global Domen: $URL"
    else
        echo "🔴 Cloudflare Tunnel: TO'XTATILGAN"
    fi
    echo "=========================================================="
}

case "$ACTION" in
    start)
        start_all
        ;;
    stop)
        stop_all
        ;;
    restart)
        stop_all
        sleep 2
        start_all
        ;;
    status|*)
        show_status
        ;;
esac
