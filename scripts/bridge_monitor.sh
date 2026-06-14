#!/bin/bash
# ============================================================
# Bridge Monitor v3.4 - 持续消费 trigger 队列并派发任务
# 每30秒轮询 status/trigger_queue/ 目录，按时间戳排序消费
# 所有任务 → 写入 workbuddy_pending/（WorkBuddy 自行轮询消费）
# v3.1: 改为目录队列消费，支持多任务并发不丢失
# v3.2: workbuddy_pending 过期回收 + 可配置轮询间隔
# v3.3: 移除 QClaw 路由（QClaw 已退役）
# v3.4: 消除 python3 -c 内联调用，统一使用 bridge_monitor_tools.py
#       (性能优化：从 7+ 次独立 Python 进程 → 每轮循环仅 2-3 次调用)
# ============================================================

set +e

BRIDGE_DIR="$HOME/workbuddy_marvis_bridge"
TRIGGER_DIR="$BRIDGE_DIR/status/trigger_queue"
LOG_FILE="$BRIDGE_DIR/logs/monitor.log"
PID_FILE="$BRIDGE_DIR/status/monitor.pid"
TOOL="$BRIDGE_DIR/scripts/bridge_monitor_tools.py"

# 一次性读取配置（仅启动时调用一次 Python）
MONITOR_INTERVAL=$(python3 "$TOOL" get-config automation.scan_interval_seconds 30 2>/dev/null)
MONITOR_INTERVAL=${MONITOR_INTERVAL:-30}

PENDING_TTL=$(python3 "$TOOL" get-config workbuddy_pending.ttl_seconds 3600 2>/dev/null)
PENDING_TTL=${PENDING_TTL:-3600}

mkdir -p "$BRIDGE_DIR/logs" "$TRIGGER_DIR"

# Docker 模式下清理上次运行残留的 PID 文件
if [ -f /.dockerenv ]; then
    rm -f "$PID_FILE" 2>/dev/null
fi

# 防止多实例
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')][monitor] 已有 Monitor 实例运行 (PID: $OLD_PID)，退出" | tee -a "$LOG_FILE"
        exit 0
    fi
fi
echo $$ > "$PID_FILE"

# 信号处理
cleanup() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')][monitor] Bridge Monitor 收到停止信号" | tee -a "$LOG_FILE"
    rm -f "$PID_FILE"
    exit 0
}
trap cleanup SIGINT SIGTERM

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')][monitor][INFO] $*" | tee -a "$LOG_FILE"
}
log_err() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')][monitor][ERROR] $*" | tee -a "$LOG_FILE"
}

# 将失败任务写入死信队列（使用工具脚本）
write_dead_letter() {
    local task_file=$1
    local reason=$2
    python3 "$TOOL" write-dead-letter "$task_file" "$reason" "$BRIDGE_DIR" 2>/dev/null
}

log "Bridge Monitor 启动 (PID: $$, 轮询间隔=${MONITOR_INTERVAL}s, Pending TTL=${PENDING_TTL}s)"

while true; do
    # ==================== 消费触发队列 ====================
    for trigger_file in $(ls -1 "$TRIGGER_DIR"/*.json 2>/dev/null | sort); do
        [ ! -f "$trigger_file" ] && continue

        # 用工具脚本一次性读取 task_file 字段
        TASK_FILE=$(python3 "$TOOL" get-task-field "$trigger_file" task_file "" 2>/dev/null)
        if [ -z "$TASK_FILE" ] || [ ! -f "$TASK_FILE" ]; then
            log_err "触发文件无效或任务文件不存在: $trigger_file"
            rm -f "$trigger_file"
            continue
        fi

        # 用工具脚本一次性读取 target_agent 和 project
        TARGET=$(python3 "$TOOL" get-task-field "$TASK_FILE" target_agent "" 2>/dev/null)
        PROJECT=$(python3 "$TOOL" get-task-field "$TASK_FILE" project claw 2>/dev/null)

        # WorkBuddy 任务写入待处理队列（工具脚本批量操作）
        PENDING_DIR="$BRIDGE_DIR/status/workbuddy_pending"
        RESULT=$(python3 "$TOOL" enqueue-pending "$TASK_FILE" "$PENDING_DIR" 2>/dev/null)
        # 输出格式: ENQUEUED|task_id|project|target_agent
        if [ $? -eq 0 ]; then
            TASK_ID=$(echo "$RESULT" | cut -d'|' -f2)
            log "WorkBuddy 任务已入队: $TASK_FILE (id=$TASK_ID, agent=$TARGET)"
        else
            log_err "任务入队失败: $TASK_FILE"
            write_dead_letter "$TASK_FILE" "bridge_monitor: enqueue_pending 失败"
        fi

        # 消费完毕，删除触发条目
        rm -f "$trigger_file"
    done

    # ==================== v3.4: workbuddy_pending 过期回收（工具脚本批量处理） ====================
    PENDING_DIR="$BRIDGE_DIR/status/workbuddy_pending"
    if [ -d "$PENDING_DIR" ]; then
        EXPIRED_OUTPUT=$(python3 "$TOOL" check-expired "$PENDING_DIR" "$PENDING_TTL" "$BRIDGE_DIR" 2>/dev/null)
        # 输出格式: EXPIRED|pending_file|age_s|dead_letter_file (每条过期任务一行)
        while IFS= read -r line; do
            case "$line" in
                EXPIRED\|*)
                    pending_file=$(echo "$line" | cut -d'|' -f2)
                    age_s=$(echo "$line" | cut -d'|' -f3)
                    log "WorkBuddy 任务过期回收: $pending_file (入队 ${age_s}s 未被消费)"
                    ;;
                OK\|*) ;;  # 无过期
            esac
        done <<< "$EXPIRED_OUTPUT"
    fi

    sleep "$MONITOR_INTERVAL"
done
