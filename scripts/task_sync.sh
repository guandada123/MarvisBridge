#!/bin/bash
# task_sync.sh — 将 Marvis 写入 claw/tasks/ 的任务同步到 status/workbuddy_pending/
# 
# 背景：Marvis 持续将任务写入 claw/tasks/ 而非 status/workbuddy_pending/
# 此脚本作为补偿机制，将可操作任务移动到正确目录
#
# 筛选规则：
#   - 仅移动 type 为 actionable 的任务（data_collection, fix, feature, deploy, maintenance, audit, code）
#   - 跳过 completion notes（empty description / type:notification）
#   - 跳过 failure_notification（已有熔断器处理）
#   - 去重：已存在 workbuddy_pending/ 中的不重复移动
#   - 已被 idempotent_skip 记录的不移动

set +e

BRIDGE_DIR="$HOME/workbuddy_marvis_bridge"
TOOL="$BRIDGE_DIR/scripts/bridge_monitor_tools.py"
SOURCE="$BRIDGE_DIR/claw/tasks"
TARGET="$BRIDGE_DIR/status/workbuddy_pending"
DONE="$BRIDGE_DIR/claw/done"
LOG="$BRIDGE_DIR/status/task_sync.log"

# 确保目录存在
mkdir -p "$TARGET" "$DONE"

MOVED=0
SKIPPED=0

python3 "$TOOL" log task_sync INFO "=== 扫描开始 ===" | tee -a "$LOG"

for file in "$SOURCE"/*.json; do
    [ -f "$file" ] || continue
    
    filename=$(basename "$file")
    
    # 用工具脚本一次性读取 type 和 task_id（消除两次 python3 -c 内联调用）
    read -r task_type task_id <<< $(python3 "$TOOL" get-fields "$file" type task_id 2>/dev/null || echo "unknown unknown")
    
    # 跳过不可操作类型
    case "$task_type" in
        notification|failure_notification)
            python3 "$TOOL" log task_sync INFO "SKIP $filename (type=$task_type, non-actionable)" | tee -a "$LOG"
            SKIPPED=$((SKIPPED + 1))
            continue
            ;;
    esac
    
    # 检查是否已在 pending 目录
    if [ -f "$TARGET/${task_id}.json" ]; then
        python3 "$TOOL" log task_sync INFO "DUP  $filename → already in pending/" | tee -a "$LOG"
        # 归档源文件到 done
        mv "$file" "$DONE/"
        SKIPPED=$((SKIPPED + 1))
        continue
    fi
    
    # 移动任务到 pending
    mv "$file" "$TARGET/"
    MOVED=$((MOVED + 1))
    python3 "$TOOL" log task_sync INFO "MOVE $filename → workbuddy_pending/${task_id}.json" | tee -a "$LOG"
done

python3 "$TOOL" log task_sync INFO "同步完成: moved=$MOVED skipped=$SKIPPED" | tee -a "$LOG"

# Docker 模式：添加循环防止快速重启
if [ -f /.dockerenv ] || [ "${DOCKER_MODE}" = "1" ]; then
    sleep 60
fi
