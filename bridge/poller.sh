#!/bin/bash
# Bridge Poller v1.0 — 近实时任务队列监控
# 用途: 每60秒扫描 workbuddy_pending/，有新任务时触发 WorkBuddy 消费
# 部署: launchd agent (com.marvis.bridge-poller.plist)

set -euo pipefail

BRIDGE_ROOT="${BRIDGE_ROOT:-$HOME/workbuddy_marvis_bridge}"
TOOL="$BRIDGE_ROOT/scripts/bridge_monitor_tools.py"
PENDING_DIR="$BRIDGE_ROOT/status/workbuddy_pending"
SIGNAL_DIR="$BRIDGE_ROOT/status/signals"
LOG_FILE="$BRIDGE_ROOT/status/poller.log"
STATE_FILE="$BRIDGE_ROOT/status/.poller_state"
INTERVAL=60

# 守护进程错误处理：记录但不退出
trap 'log "脚本异常 (line $LINENO, exit=$?)"' ERR

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"
}

# 获取当前队列快照（文件名列表 + 目录 mtime 的 hash）
# 目录 mtime 会在任何文件增删时更新，确保不会漏检窗口内的快速变更
current_snapshot() {
    (
        ls "$PENDING_DIR"/*.json 2>/dev/null | sort
        stat -f "%m" "$PENDING_DIR" 2>/dev/null || echo "0"
    ) | md5 -q 2>/dev/null || echo "empty"
}

# 触发 WorkBuddy 消费
trigger_workbuddy() {
    local consumer="$BRIDGE_ROOT/bridge/workbuddy_consumer.sh"
    
    if [ -x "$consumer" ]; then
        log "TRIGGER: 启动 Bridge Consumer 消费 ${task_count} 个任务"
        bash "$consumer" >> "$LOG_FILE" 2>&1 &
        log "TRIGGER: Consumer 已后台启动 (PID: $!)"
    else
        log "TRIGGER: Consumer 脚本不可用 ($consumer)，写入降级信号"
        echo "$(date +%s)" > "$BRIDGE_ROOT/status/.trigger_pending"
    fi
    
    # macOS 通知
    osascript -e "display notification \"队列中有 ${task_count} 个待消费任务\" with title \"Bridge Poller\" sound name \"Glass\"" 2>/dev/null
}

# 主循环
log "=== Bridge Poller 启动 (间隔 ${INTERVAL}s) ==="

while true; do
    snapshot=$(current_snapshot)
    prev_snapshot=$(cat "$STATE_FILE" 2>/dev/null || echo "")
    
    if [ "$snapshot" != "$prev_snapshot" ]; then
        task_count=$(ls "$PENDING_DIR"/*.json 2>/dev/null | wc -l | tr -d ' ')
        echo "$snapshot" > "$STATE_FILE"
        
        if [ "$task_count" -gt 0 ]; then
            log "检测到 ${task_count} 个待消费任务"
            trigger_workbuddy
        fi
        
        # 生成 Marvis 速览摘要（省掉读完整 STATUS.md）
        {
            echo "# $(date '+%Y-%m-%d %H:%M')"
            echo "pending=$task_count"
            ls "$SIGNAL_DIR"/done_*.json 2>/dev/null | wc -l | tr -d ' ' | xargs echo "signals="
            ls "$PENDING_DIR"/*.json 2>/dev/null | while read f; do
                read -r tid pid prio <<< $(python3 "$TOOL" get-fields "$f" task_id project priority 2>/dev/null || echo "? ? ?")
                echo "  ${tid} | ${pid} | ${prio}"
            done
        } > "$BRIDGE_ROOT/status/.marvis_summary"
    fi
    
    # 清理状态: 队列空时重置
    if [ "$snapshot" = "empty" ] && [ "$prev_snapshot" != "empty" ]; then
        log "队列已清空"
        rm -f "$STATE_FILE"
    fi
    
    sleep "$INTERVAL"
done
