#!/bin/bash
# ============================================================
# Bridge 全链路健康检查 v1.0
# 检查 watcher、monitor、QClaw 全部存活，输出健康报告
#
# 用法:
#   ./health_check.sh          # 终端输出
#   ./health_check.sh --json   # JSON 格式（供监控系统消费）
#   ./health_check.sh --quiet  # 静默模式，退出码表示健康状态
# ============================================================

set +e

BRIDGE_DIR="$HOME/workbuddy_marvis_bridge"
STATUS_DIR="$BRIDGE_DIR/status"

OUTPUT_JSON=false
QUIET_MODE=false
for arg in "$@"; do
    case "$arg" in
        --json)  OUTPUT_JSON=true ;;
        --quiet) QUIET_MODE=true ;;
    esac
done

# ==================== 检查项 ====================

# 使用并行索引数组替代 declare -A（bash 3.2 不兼容关联数组）
CHECK_KEYS=()
CHECK_VALS=()
ALL_HEALTHY=true
ISSUES=()

# 辅助：安全添加检查结果
add_check() {
    local key="$1"
    local val="$2"
    CHECK_KEYS+=("$key")
    CHECK_VALS+=("$val")
}

# --- 1. watcher 进程 ---
WATCHER_PID_FILE="$STATUS_DIR/watcher.pid"
if [ -f "$WATCHER_PID_FILE" ]; then
    WATCHER_PID=$(cat "$WATCHER_PID_FILE")
    if kill -0 "$WATCHER_PID" 2>/dev/null; then
        add_check "watcher" "healthy|PID=$WATCHER_PID"
    else
        add_check "watcher" "dead|PID文件存在但进程不存在"
        ALL_HEALTHY=false
        ISSUES+=("watcher 进程已死亡 (PID=$WATCHER_PID)")
    fi
else
    add_check "watcher" "missing|无 PID 文件"
    ALL_HEALTHY=false
    ISSUES+=("watcher 未启动 (无 PID 文件)")
fi

# --- 2. monitor 进程 ---
MONITOR_PID_FILE="$STATUS_DIR/monitor.pid"
if [ -f "$MONITOR_PID_FILE" ]; then
    MONITOR_PID=$(cat "$MONITOR_PID_FILE")
    if kill -0 "$MONITOR_PID" 2>/dev/null; then
        add_check "monitor" "healthy|PID=$MONITOR_PID"
    else
        add_check "monitor" "dead|PID文件存在但进程不存在"
        ALL_HEALTHY=false
        ISSUES+=("monitor 进程已死亡 (PID=$MONITOR_PID)")
    fi
else
    add_check "monitor" "missing|无 PID 文件"
    ALL_HEALTHY=false
    ISSUES+=("monitor 未启动 (无 PID 文件)")
fi

# --- 3. fswatch 进程 ---
FSWATCH_COUNT=$(pgrep -f "fswatch.*workbuddy_pending" 2>/dev/null | wc -l | tr -d ' ')
if [ "$FSWATCH_COUNT" -gt 0 ]; then
    add_check "fswatch" "healthy|${FSWATCH_COUNT} 个进程"
else
    add_check "fswatch" "dead|无 fswatch 进程"
    ALL_HEALTHY=false
    ISSUES+=("fswatch 未运行，文件监听已停止")
fi

# --- 4. 心跳 ---
HEARTBEAT_FILE="$STATUS_DIR/heartbeat"
if [ -f "$HEARTBEAT_FILE" ]; then
    LAST_HEARTBEAT=$(cat "$HEARTBEAT_FILE")
    # 跨平台：将 ISO8601 时间戳转为 epoch 秒
    if [[ "$(uname)" == "Darwin" ]]; then
        HEARTBEAT_EPOCH=$(date -j -f "%Y-%m-%dT%H:%M:%S%z" "$LAST_HEARTBEAT" +%s 2>/dev/null || echo 0)
    else
        HEARTBEAT_EPOCH=$(date -d "$LAST_HEARTBEAT" +%s 2>/dev/null || echo 0)
    fi
    NOW_EPOCH=$(date +%s)
    HEARTBEAT_AGE=$((NOW_EPOCH - HEARTBEAT_EPOCH))
    if [ "$HEARTBEAT_AGE" -lt 180 ]; then
        add_check "heartbeat" "healthy|${HEARTBEAT_AGE}s 前"
    else
        add_check "heartbeat" "stale|${HEARTBEAT_AGE}s 未更新"
        ALL_HEALTHY=false
        ISSUES+=("心跳停滞 ${HEARTBEAT_AGE}s，watcher 可能卡死")
    fi
else
    add_check "heartbeat" "missing|无心跳文件"
    ALL_HEALTHY=false
    ISSUES+=("无心跳文件")
fi

# --- 5. trigger_queue 积压 ---
TRIGGER_DIR="$STATUS_DIR/trigger_queue"
if [ -d "$TRIGGER_DIR" ]; then
    TRIGGER_COUNT=$(ls -1 "$TRIGGER_DIR"/*.json 2>/dev/null | wc -l | tr -d ' ')
    if [ "$TRIGGER_COUNT" -gt 20 ]; then
        add_check "trigger_queue" "backlogged|${TRIGGER_COUNT} 条积压"
        ISSUES+=("trigger_queue 积压 ${TRIGGER_COUNT} 条，monitor 可能处理不过来")
    else
        add_check "trigger_queue" "healthy|${TRIGGER_COUNT} 条"
    fi
else
    add_check "trigger_queue" "missing|目录不存在"
fi

# --- 6. dead_letter ---
DEAD_TOTAL=0
for proj in claw quant; do
    DL_DIR="$BRIDGE_DIR/$proj/dead_letter"
    if [ -d "$DL_DIR" ]; then
        cnt=$(ls -1 "$DL_DIR"/*.json 2>/dev/null | wc -l | tr -d ' ')
        DEAD_TOTAL=$((DEAD_TOTAL + cnt))
    fi
done
if [ "$DEAD_TOTAL" -gt 50 ]; then
    add_check "dead_letter" "warning|${DEAD_TOTAL} 封死信"
    ISSUES+=("死信队列累积 ${DEAD_TOTAL} 封，建议清理")
else
    add_check "dead_letter" "healthy|${DEAD_TOTAL} 封"
fi

# --- 7. workbuddy_pending 积压 ---
PENDING_DIR="$STATUS_DIR/workbuddy_pending"
if [ -d "$PENDING_DIR" ]; then
    PENDING_COUNT=$(ls -1 "$PENDING_DIR"/*.json 2>/dev/null | wc -l | tr -d ' ')
    if [ "$PENDING_COUNT" -gt 10 ]; then
        add_check "workbuddy_pending" "backlogged|${PENDING_COUNT} 条待处理"
        ISSUES+=("WorkBuddy 待处理队列积压 ${PENDING_COUNT} 条")
    else
        add_check "workbuddy_pending" "healthy|${PENDING_COUNT} 条"
    fi
else
    add_check "workbuddy_pending" "healthy|0 条 (目录未创建)"
fi

# ==================== 输出 ====================

if $OUTPUT_JSON; then
    # v1.2: 使用 Python 工具生成安全 JSON（消除手动拼接风险）
    python3 "$BRIDGE_DIR/scripts/bridge_monitor_tools.py" gen-health-json "$BRIDGE_DIR" 2>/dev/null
elif $QUIET_MODE; then
    $ALL_HEALTHY && exit 0 || exit 1
else
    echo "========================================"
    echo "  Bridge 全链路健康检查"
    echo "  $(date '+%Y-%m-%d %H:%M:%S')"
    echo "========================================"
    echo ""
    for i in "${!CHECK_KEYS[@]}"; do
        key="${CHECK_KEYS[$i]}"
        val="${CHECK_VALS[$i]}"
        IFS="|" read -r status detail <<< "$val"
        case "$status" in
            healthy)    icon="✅" ;;
            warning)    icon="⚠️" ;;
            stale)      icon="⏸️" ;;
            backlogged) icon="📊" ;;
            dead)       icon="❌" ;;
            missing)    icon="❌" ;;
            unknown)    icon="❓" ;;
            *)          icon="❓" ;;
        esac
        printf "  %s %-20s %s\n" "$icon" "$key" "$detail"
    done
    echo ""
    if [ ${#ISSUES[@]} -gt 0 ]; then
        echo "问题 (${#ISSUES[@]}):"
        for issue in "${ISSUES[@]}"; do
            echo "  ⚠️  $issue"
        done
        echo ""
    fi
    if $ALL_HEALTHY; then
        echo "结论: 全部健康 ✅"
    else
        echo "结论: 有组件异常，需要处理 ❌"
    fi
fi
