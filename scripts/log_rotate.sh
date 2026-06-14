#!/bin/bash
# ============================================================
# Bridge 日志轮转脚本 v1.1
# 用法: ./log_rotate.sh [--max-size-mb 50] [--keep 7]
# v1.1: 跨平台兼容（macOS/BSD + Linux/GNU），移除 bc 依赖
# ============================================================

set +e

BRIDGE_DIR="${BRIDGE_DIR:-$HOME/workbuddy_marvis_bridge}"
LOGS_DIR="$BRIDGE_DIR/logs"
ARCHIVE_DIR="$LOGS_DIR/archive"

MAX_SIZE_MB=50
KEEP_DAYS=7

# 解析参数
while [[ $# -gt 0 ]]; do
    case "$1" in
        --max-size-mb) MAX_SIZE_MB="$2"; shift 2 ;;
        --keep)        KEEP_DAYS="$2"; shift 2 ;;
        *)             echo "未知参数: $1"; exit 1 ;;
    esac
done

mkdir -p "$ARCHIVE_DIR"

MAX_SIZE_BYTES=$((MAX_SIZE_MB * 1024 * 1024))
NOW=$(date '+%Y%m%d_%H%M%S')

# 跨平台检测 OS 类型
if [[ "$(uname)" == "Darwin" ]]; then
    # macOS / BSD
    get_size() { stat -f%z "$1" 2>/dev/null || echo 0; }
else
    # Linux / GNU
    get_size() { stat -c%s "$1" 2>/dev/null || echo 0; }
fi

# 遍历日志文件
for logfile in "$LOGS_DIR"/*.log; do
    [ -f "$logfile" ] || continue

    size=$(get_size "$logfile")

    if [ "$size" -gt "$MAX_SIZE_BYTES" ]; then
        basename=$(basename "$logfile" .log)
        archived="$ARCHIVE_DIR/${basename}_${NOW}.log.gz"
        gzip -c "$logfile" > "$archived"
        : > "$logfile"  # 清空原文件
        # 跨平台文件大小格式化（纯 bash 整数运算，无需 bc）
        size_mb=$((size / 1024 / 1024))
        echo "[$(date '+%Y-%m-%d %H:%M:%S')][log_rotate] $logfile 已轮转 → $archived (${size_mb}MB)"
    fi
done

# 清理过期归档（KEEP_DAYS 天前，跨平台兼容）
if [[ "$(uname)" == "Darwin" ]]; then
    find "$ARCHIVE_DIR" -name "*.log.gz" -mtime "+${KEEP_DAYS}" -delete 2>/dev/null
else
    find "$ARCHIVE_DIR" -name "*.log.gz" -mtime "+${KEEP_DAYS}" -delete 2>/dev/null
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')][log_rotate] 轮转完成 (max=${MAX_SIZE_MB}MB, keep=${KEEP_DAYS}d)"
