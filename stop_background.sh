#!/usr/bin/env bash
# Agentni to'xtatish
pkill -f "uvicorn app:app" 2>/dev/null || true
echo "🛑 Agent va veb server to'xtatildi."
