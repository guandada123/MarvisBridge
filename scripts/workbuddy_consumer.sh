#!/bin/bash
# ============================================================
# WorkBuddy Consumer — 消费 workbuddy_pending 队列中的任务
# 功能: 读取 pending/*.json → 执行任务 → 写结果 → 归档
# 调用: launchd 定时触发或手动执行
# v1.0.0 - 2026-06-16
# ============================================================

set -euo pipefail

BRIDGE_DIR="${HOME}/workbuddy_marvis_bridge"
TOOL="${BRIDGE_DIR}/scripts/bridge_monitor_tools.py"
PENDING_DIR="${BRIDGE_DIR}/status/workbuddy_pending"
ARCHIVE_DIR="${BRIDGE_DIR}/status/archive"
RESULTS_DIR="${BRIDGE_DIR}/status/results"
LOCK_NAME="workbuddy_consumer"
LOG_FILE="${BRIDGE_DIR}/logs/consumer.log"
PID_FILE="${BRIDGE_DIR}/status/consumer.pid"

INTERVAL=30  # 扫描间隔（秒），launchd 模式下只执行一次

mkdir -p "${ARCHIVE_DIR}" "${RESULTS_DIR}" "${BRIDGE_DIR}/logs" 2>/dev/null
echo $$ > "${PID_FILE}"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "${LOG_FILE}"
}

# === 获取互斥锁 ===
python3 "$TOOL" acquire-lock "$LOCK_NAME" 60 2>/dev/null || {
    log "⚠️ 另一个 Consumer 实例正在运行，退出"
    rm -f "${PID_FILE}"
    exit 0
}

log "=== Bridge Consumer 启动 ==="

cleanup() {
    log "=== Bridge Consumer 停止 ==="
    rm -f "${PID_FILE}" "${BRIDGE_DIR}/status/locks/${LOCK_NAME}.lock" \
          "${BRIDGE_DIR}/status/locks/${LOCK_NAME}.pid" 2>/dev/null
    exit 0
}
trap cleanup SIGINT SIGTERM

# === 处理单个任务 ===
process_task() {
    local task_file="$1"
    local task_id=""
    local project=""
    local task_type=""
    local title=""
    local source=""
    local now
    now=$(date '+%Y-%m-%d %H:%M:%S')

    # 读取基本字段
    task_id=$(python3 "$TOOL" get-task-field "$task_file" task_id "" 2>/dev/null)
    project=$(python3 "$TOOL" get-task-field "$task_file" project "claw" 2>/dev/null)
    task_type=$(python3 "$TOOL" get-task-field "$task_file" type "unknown" 2>/dev/null)
    title=$(python3 "$TOOL" get-task-field "$task_file" title "未知任务" 2>/dev/null)
    # shellcheck disable=SC2034
    source=$(python3 "$TOOL" get-task-field "$task_file" source "unknown" 2>/dev/null)

    [ -z "$task_id" ] && { log "任务 ID 缺失，跳过: $task_file"; return 1; }

    local result_file="${RESULTS_DIR}/${task_id}.json"
    local archive_file
    archive_file="${ARCHIVE_DIR}/${task_id}_$(date +%s).json"
    local result_status="completed"

    # --- 按类型分发处理 ---
    case "$task_type" in
        data_collection|data_collect|market_snapshot)
            log "处理 data_collection 任务: $task_id ($title)"

            # 提取 OCR 数据和截图路径
            local ocr_text
            local screenshot
            ocr_text=$(python3 "$TOOL" get-task-field "$task_file" "params.ocr_text" "" 2>/dev/null || echo "")
            screenshot=$(python3 "$TOOL" get-task-field "$task_file" "params.screenshot" "" 2>/dev/null || echo "")

            # 将原始数据保存到项目 raw_data 目录
            local raw_dir="${BRIDGE_DIR}/${project}/raw_data"
            mkdir -p "$raw_dir" 2>/dev/null

            # 写结构化结果 JSON（替代 inline heredoc）
            python3 "$TOOL" write-data-collection-result \
                "$task_file" "$task_id" "$project" "$title" \
                "$ocr_text" "$screenshot" "$result_file" "$raw_dir" "$now" 2>/dev/null
            result_status="completed"
            ;;

        custom|maintenance|test)
            log "处理 ${task_type} 任务: $task_id ($title)"
            # 简单任务：直接记录完成状态（替代 inline heredoc）
            python3 "$TOOL" write-simple-result \
                "$task_file" "$task_id" "$project" "$title" \
                "$result_file" "$now" 2>/dev/null
            ;;

        *)
            log "未支持的任务类型: $task_type (task=$task_id)，跳过"
            return 1
            ;;
    esac

    # 更新任务状态为 done
    python3 "$TOOL" update-field "$task_file" status "completed" 2>/dev/null || true

    # 归档任务文件
    mv "$task_file" "$archive_file" 2>/dev/null && {
        log "已归档: $task_id → $(basename "$archive_file")"
    } || {
        log "归档失败: $task_id"
    }

    log "消费完成: $task_id ($title) [$result_status]"
    return 0
}

# === 主循环 ===
if [ "$#" -gt 0 ] && [ "$1" = "--once" ]; then
    # 一次性模式：处理所有 pending 任务后退出
    log "一次性模式: 扫描 ${PENDING_DIR}"
    processed=0
    while IFS= read -r task_file; do
        [ -f "$task_file" ] || continue
        process_task "$task_file" && processed=$((processed + 1))
    done < <(find "$PENDING_DIR" -name "*.json" -maxdepth 1 -type f 2>/dev/null | sort)
    log "=== Bridge Consumer 完成 (处理 ${processed} 个任务) ==="
else
    # 持续运行模式（由 launchd 管理）
    log "持续模式 (间隔 ${INTERVAL}s)"
    while true; do
        has_work=false
        while IFS= read -r task_file; do
            [ -f "$task_file" ] || continue
            process_task "$task_file" && has_work=true
        done < <(find "$PENDING_DIR" -name "*.json" -maxdepth 1 -type f 2>/dev/null | sort)

        if [ "$has_work" = false ]; then
            log "空闲，等待 ${INTERVAL}s ..."
        fi
        sleep "${INTERVAL}"
    done
fi

cleanup
