#!/bin/bash
# ============================================================
# Bridge 死信队列定期清理 v1.1
# v1.1: 跨平台兼容（macOS/BSD + Linux/GNU），消除 python3 -c 内联
# ============================================================

set +e

BRIDGE_DIR="$HOME/workbuddy_marvis_bridge"
CONFIG_FILE="$BRIDGE_DIR/shared/config/config.json"
ARCHIVE_DIR="$BRIDGE_DIR/status/dead_letter_archive"
TOOL="$BRIDGE_DIR/scripts/bridge_monitor_tools.py"

DRY_RUN=false
CLEAR_ALL=false
for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=true ;;
        --all)     CLEAR_ALL=true ;;
    esac
done

# 读取保留天数（使用工具脚本）
RETENTION_DAYS=$(python3 "$TOOL" get-config dead_letter_queue.retention_days 30 2>/dev/null)
RETENTION_DAYS=${RETENTION_DAYS:-30}

# 跨平台日期计算
if [[ "$(uname)" == "Darwin" ]]; then
    # macOS / BSD
    get_cutoff_epoch() { date -v-${1}d +%s; }
else
    # Linux / GNU
    get_cutoff_epoch() { date -d "${1} days ago" +%s; }
fi

# 跨平台获取文件 mtime
if [[ "$(uname)" == "Darwin" ]]; then
    get_mtime() { stat -f %m "$1" 2>/dev/null || echo 0; }
else
    get_mtime() { stat -c %Y "$1" 2>/dev/null || echo 0; }
fi

TOTAL_DELETED=0
TOTAL_FREED_KB=0

cleanup_project() {
    local project=$1
    local dl_dir="$BRIDGE_DIR/$project/dead_letter"
    [ ! -d "$dl_dir" ] && return

    local cutoff_epoch
    if $CLEAR_ALL; then
        cutoff_epoch=$(date +%s)
    else
        cutoff_epoch=$(get_cutoff_epoch "$RETENTION_DAYS")
    fi

    for f in "$dl_dir"/*.json; do
        [ ! -f "$f" ] && continue

        local mtime_epoch=$(get_mtime "$f")

        if [ "$mtime_epoch" -lt "$cutoff_epoch" ] || $CLEAR_ALL; then
            local size_kb=$(du -k "$f" | cut -f1)
            local fname=$(basename "$f")

            if $DRY_RUN; then
                echo "  [DRY-RUN] 将清理: $project/dead_letter/$fname (${size_kb}KB)"
            else
                # 归档一份再删除
                mkdir -p "$ARCHIVE_DIR/$project"
                cp "$f" "$ARCHIVE_DIR/$project/${fname}.$(date +%Y%m%d)"
                rm -f "$f"
                TOTAL_DELETED=$((TOTAL_DELETED + 1))
                TOTAL_FREED_KB=$((TOTAL_FREED_KB + size_kb))
                echo "  已清理: $project/dead_letter/$fname (${size_kb}KB)"
            fi
        fi
    done
}

echo "========================================"
echo "  死信队列清理"
echo "  保留期限: ${RETENTION_DAYS} 天"
if $DRY_RUN; then echo "  模式: DRY RUN（预览）"; fi
if $CLEAR_ALL; then echo "  模式: 清空全部"; fi
echo "========================================"
echo ""

cleanup_project "claw"
cleanup_project "quant"

echo ""
if $DRY_RUN; then
    echo "预览完成。执行清理请去掉 --dry-run"
else
    echo "清理完成: ${TOTAL_DELETED} 封死信，释放 ${TOTAL_FREED_KB}KB"
    echo "归档位置: $ARCHIVE_DIR"
fi
