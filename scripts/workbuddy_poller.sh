#!/bin/bash
# ============================================================
# WorkBuddy Side Poller — 监听 Marvis 写入的待消费任务
# 间隔: 60s | 日志: status/workbuddy_poller.log
# ============================================================

BRIDGE_DIR="${HOME}/workbuddy_marvis_bridge"
TOOL="${BRIDGE_DIR}/scripts/bridge_monitor_tools.py"
PENDING_DIR="${BRIDGE_DIR}/status/workbuddy_pending"
TRIGGER_FILE="${BRIDGE_DIR}/status/workbuddy_trigger"
SIGNAL_FILE="${BRIDGE_DIR}/status/signals/workbuddy_poller_active"
LOG_FILE="${BRIDGE_DIR}/status/workbuddy_poller.log"
PID_FILE="${BRIDGE_DIR}/status/workbuddy_poller.pid"

INTERVAL=60
LAST_HASH=""

# === 初始化 ===
mkdir -p "${PENDING_DIR}" "${BRIDGE_DIR}/status/signals" 2>/dev/null
echo $$ > "${PID_FILE}"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] === WorkBuddy Poller 启动 (PID $$, 间隔 ${INTERVAL}s) ===" >> "${LOG_FILE}"

# === 单次轮询 ===
poll() {
    # 统计待消费任务
    local count=0
    if [ -d "${PENDING_DIR}" ]; then
        count=$(ls "${PENDING_DIR}"/*.json 2>/dev/null | wc -l | tr -d ' ')
    fi

    # 计算当前目录 hash（只对文件名和大小做指纹）
    local current_hash
    if [ "${count}" -gt 0 ]; then
        current_hash=$(ls -la "${PENDING_DIR}"/*.json 2>/dev/null | md5)
    else
        current_hash="empty"
    fi

    # 检测变化
    if [ "${current_hash}" != "${LAST_HASH}" ]; then
        local timestamp=$(date '+%Y-%m-%d %H:%M:%S')

        if [ "${LAST_HASH}" = "" ]; then
            # 首次启动 — 只记录不通知
            echo "[${timestamp}] 首次扫描: ${count} 个任务排队" >> "${LOG_FILE}"
        elif [ "${count}" -gt 0 ] && [ "${current_hash}" != "${LAST_HASH}" ]; then
            # 新任务到达
            echo "[${timestamp}] 🔔 新任务到达: ${count} 个待消费" >> "${LOG_FILE}"

            # 写信号文件 (供 Bridge Monitor automation 读取)
            echo "${timestamp}" > "${TRIGGER_FILE}"

            # 写活跃信号
            echo "${timestamp} | tasks=${count}" > "${SIGNAL_FILE}"

            # 跨平台通知（自动检测 macOS/Linux，同时尝试飞书 Webhook）
            local task_list=""
            for f in "${PENDING_DIR}"/*.json; do
                [ -f "$f" ] || continue
                local title=$(python3 "$TOOL" get-task-field "${f}" title "未知任务" 2>/dev/null)
                task_list="${task_list}• ${title}\n"
            done

            python3 "$BRIDGE_DIR/scripts/bridge_notify.py" \
                "📥 Bridge 新任务 (${count}个)" \
                "${task_list}" 2>/dev/null || true

        else
            # 任务被消费完毕
            echo "[${timestamp}] ✅ 队列已清空" >> "${LOG_FILE}"
            rm -f "${TRIGGER_FILE}"
            echo "${timestamp} | idle" > "${SIGNAL_FILE}"
        fi

        LAST_HASH="${current_hash}"
    fi
}

# === 主循环 ===
cleanup() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] === Poller 停止 ===" >> "${LOG_FILE}"
    rm -f "${PID_FILE}" "${SIGNAL_FILE}"
    exit 0
}
trap cleanup SIGINT SIGTERM

while true; do
    poll
    sleep "${INTERVAL}"
done
