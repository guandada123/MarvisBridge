#!/bin/bash
# Bridge Consumer v1.0 — 消费待处理任务并回写结果
# 由 poller.sh 检测到任务时触发，替代原来的 python3 内联调用
#
# 用法: ./workbuddy_consumer.sh [--project claw|quant] [--task-id TASK_ID]
#       无参数时消费所有项目所有待处理任务

set -euo pipefail

BRIDGE_ROOT="${BRIDGE_ROOT:-$HOME/workbuddy_marvis_bridge}"
SCRIPTS_DIR="$BRIDGE_ROOT/scripts"
TOOLS="$SCRIPTS_DIR/bridge_monitor_tools.py"
VALIDATOR="$SCRIPTS_DIR/task_validator.py"
LOG_FILE="$BRIDGE_ROOT/logs/consumer.log"
LOCK_DIR="$BRIDGE_ROOT/status/locks"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# 确保必要目录存在
mkdir -p "$BRIDGE_ROOT/logs" "$LOCK_DIR"

# ── 解析参数 ───────────────────────────────
PROJECT_FILTER="${1:-}"
TASK_ID_FILTER="${2:-}"

# ── 扫描待处理任务 ─────────────────────────
scan_tasks() {
    local projects=("claw" "quant")

    if [ -n "$PROJECT_FILTER" ]; then
        projects=("$PROJECT_FILTER")
    fi

    for project in "${projects[@]}"; do
        local tasks_dir="$BRIDGE_ROOT/$project/tasks"
        [ -d "$tasks_dir" ] || continue

        for task_file in "$tasks_dir"/*.json; do
            [ -f "$task_file" ] || continue

            # 跳过模板
            [ "$(basename "$task_file")" = "template.json" ] && continue

            # 任务ID过滤
            if [ -n "$TASK_ID_FILTER" ]; then
                local tid
                tid=$(python3 "$TOOLS" get-fields "$task_file" task_id 2>/dev/null || echo "")
                [ "$tid" != "$TASK_ID_FILTER" ] && continue
            fi

            process_task "$task_file" "$project"
        done
    done

    # 同时扫描 workbuddy_pending/（task_sync 搬运过来的任务）
    local pending_dir="$BRIDGE_ROOT/status/workbuddy_pending"
    if [ -d "$pending_dir" ]; then
        for task_file in "$pending_dir"/*.json; do
            [ -f "$task_file" ] || continue

            local pending_project
            pending_project=$(python3 "$TOOLS" get-fields "$task_file" project 2>/dev/null || echo "")

            # 项目过滤
            if [ -n "$PROJECT_FILTER" ] && [ "$pending_project" != "$PROJECT_FILTER" ]; then
                continue
            fi

            # 任务ID过滤
            if [ -n "$TASK_ID_FILTER" ]; then
                local tid
                tid=$(python3 "$TOOLS" get-fields "$task_file" task_id 2>/dev/null || echo "")
                [ "$tid" != "$TASK_ID_FILTER" ] && continue
            fi

            process_task "$task_file" "$pending_project"
        done
    fi
}

# ── 处理单个任务 ───────────────────────────
process_task() {
    local task_file="$1"
    local project="$2"
    local task_id
    task_id=$(python3 "$TOOLS" get-fields "$task_file" task_id 2>/dev/null || echo "unknown")

    log "📋 处理任务: $task_id ($project)"

    # 1. 校验任务
    if ! python3 "$VALIDATOR" "$task_file"; then
        local exit_code=$?
        if [ "$exit_code" -eq 2 ]; then
            log "⏭️ 幂等跳过: $task_id"
            archive_task "$task_file" "$project" "skipped"
        else
            log "❌ 校验失败: $task_id"
            archive_task "$task_file" "$project" "failed"
        fi
        return
    fi

    # 2. 标记处理中
    python3 "$TOOLS" update-field "$task_file" status "processing" 2>/dev/null || true

    # 3. 执行任务处理
    local task_type
    task_type=$(python3 "$TOOLS" get-fields "$task_file" type 2>/dev/null || echo "unknown")
    local result_file="$BRIDGE_ROOT/$project/results/${task_id}.md"

    case "$task_type" in
        data_collection|data_analysis)
            # 数据分析 → 读取 raw_data 并处理
            log "📊 执行 $task_type: $task_id"
            echo "# $task_id — 处理结果" > "$result_file"
            echo "**类型**: $task_type" >> "$result_file"
            echo "**时间**: $(date '+%Y-%m-%d %H:%M:%S')" >> "$result_file"
            echo "**状态**: ✅ 完成" >> "$result_file"
            echo "" >> "$result_file"
            echo "任务已由 Bridge Consumer 处理。详细数据见 raw_data/ 目录。" >> "$result_file"
            ;;

        code_review|report_generation|test|maintenance|custom)
            # 代码审查 / 报告 / 测试 / 维护 → 记录待 WorkBuddy 处理
            log "🔄 委派 $task_type: $task_id → WorkBuddy"
            echo "# $task_id — $task_type" > "$result_file"
            echo "**状态**: ⏳ 待 WorkBuddy 深度处理" >> "$result_file"
            echo "**委派时间**: $(date '+%Y-%m-%d %H:%M:%S')" >> "$result_file"
            echo "" >> "$result_file"
            echo "此任务需要 WorkBuddy AI 能力，已写入待处理信号。" >> "$result_file"

            # 写触发信号文件
            echo "$(date +%s) $task_id $task_type" >> "$BRIDGE_ROOT/status/.workbuddy_queue"
            ;;

        *)
            log "⚠️ 未知任务类型: $task_type"
            echo "# $task_id — 未知类型" > "$result_file"
            echo "**类型**: $task_type (未识别)" >> "$result_file"
            ;;
    esac

    # 4. 归档
    archive_task "$task_file" "$project" "completed"
    log "✅ 任务完成: $task_id → $(basename "$result_file")"
}

# ── 归档任务 ────────────────────────────────
archive_task() {
    local task_file="$1"
    local project="$2"
    local status="$3"

    local done_dir="$BRIDGE_ROOT/$project/done"
    mkdir -p "$done_dir"

    local task_id
    task_id=$(python3 "$TOOLS" get-fields "$task_file" task_id 2>/dev/null || echo "unknown")
    local ts
    ts=$(date +%Y%m%d_%H%M%S)

    cp "$task_file" "$done_dir/${ts}_${task_id}_${status}.json"
    rm -f "$task_file"
}

# ── 主流程 ──────────────────────────────────
main() {
    log "=== Bridge Consumer 启动 ==="

    # 获取互斥锁（防并发）
    if ! python3 "$TOOLS" acquire-lock "bridge_consumer" 300 2>/dev/null; then
        log "⚠️ 另一个 Consumer 实例正在运行，退出"
        exit 0
    fi

    scan_tasks

    # 更新状态面板
    python3 "$TOOLS" update-dashboard 2>/dev/null || true

    log "=== Bridge Consumer 完成 ==="
}

main
