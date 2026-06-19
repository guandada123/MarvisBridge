#!/bin/bash
# Feishu Q&A Bot 看门狗 — 每5分钟检查，挂掉自动重启
LOG_FILE="$HOME/workbuddy_marvis_bridge/logs/feishu_qa_bot_watchdog.log"
BOT_DIR="$HOME/workbuddy_marvis_bridge"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"
}

if pgrep -f "feishu_qa_bot.py" >/dev/null 2>&1; then
    # Bot is alive, everything fine
    exit 0
fi

log "⚠️ Bot 未运行，正在重启..."
cd "$BOT_DIR" && nohup python3 scripts/feishu_qa_bot.py > /dev/null 2>&1 &
BOT_PID=$!
sleep 2

if kill -0 $BOT_PID 2>/dev/null; then
    log "✅ Bot 重启成功 (PID $BOT_PID)"
else
    log "❌ Bot 重启失败"
fi
