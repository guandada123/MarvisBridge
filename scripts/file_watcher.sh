#!/bin/bash
# ============================================================
# Marvis-WorkBuddy Bridge 文件监听脚本 v3.1
# - 移除 set -e，子进程崩溃不影响主进程
# - fswatch 存活检测 + 自动重拉
# - 每60s心跳写入 status/heartbeat
# - 统一日志格式：[时间][来源][级别] 消息
# - v3.1 加固：trigger 目录队列替代单文件（避免多任务并发覆盖丢失）
#
# 用法:
#   前台运行:  ./file_watcher.sh
#   后台运行:  nohup ./file_watcher.sh &
#   停止:      kill $(cat ~/workbuddy_marvis_bridge/status/watcher.pid)
# ============================================================

set +e  # 关键修改：子进程失败不退出主进程

# 确保 pipe subshell 继承完整 PATH（Marvis 受限环境修复）
export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

BRIDGE_DIR="$HOME/workbuddy_marvis_bridge"
TOOL="$BRIDGE_DIR/scripts/bridge_monitor_tools.py"
STATUS_DIR="$BRIDGE_DIR/status"
LOGS_DIR="$BRIDGE_DIR/logs"
PID_FILE="$STATUS_DIR/watcher.pid"
TRIGGER_DIR="$STATUS_DIR/trigger_queue"   # 目录队列替代单文件，避免多任务并发覆盖丢失
HEARTBEAT_FILE="$STATUS_DIR/heartbeat"
LOG_FILE="$LOGS_DIR/watcher.log"

# 确保目录存在
mkdir -p "$STATUS_DIR" "$LOGS_DIR"

# 去重缓存：文件系统级去重（兼容 bash 3.2，不依赖 declare -A 关联数组）
DEDUP_DIR="$STATUS_DIR/.dedup_cache"
DEDUP_TTL=300  # 同一文件 300 秒内不重复触发
mkdir -p "$DEDUP_DIR"

# 去重检查：同一路径在 DEDUP_TTL 秒内仅第一次放行
# 返回 0 = 通过(未处理过/已过期)，返回 1 = 跳过(仍在去重窗口内)
dedup_check() {
    local event_path="$1"
    # 生成缓存 key：取 md5 摘要，无 md5 则用路径的十六进制编码
    local cache_key
    if command -v md5 &>/dev/null; then
        cache_key=$(printf '%s' "$event_path" | md5 -q 2>/dev/null)
    elif command -v shasum &>/dev/null; then
        cache_key=$(printf '%s' "$event_path" | shasum -a 256 2>/dev/null | cut -d' ' -f1)
    else
        # 兜底：路径转十六进制
        cache_key=$(printf '%s' "$event_path" | xxd -p 2>/dev/null | tr -d '\n')
    fi
    [ -z "$cache_key" ] && cache_key=$(echo "$event_path" | sed 's/[^a-zA-Z0-9._-]/_/g')
    
    local cache_file="$DEDUP_DIR/$cache_key"
    
    if [ -f "$cache_file" ]; then
        local expire_ts=0
        expire_ts=$(cat "$cache_file" 2>/dev/null)
        [ -z "$expire_ts" ] && expire_ts=0
        local now
        now=$(date +%s)
        # 仍在去重窗口内 → 跳过
        if [ "$now" -lt "$expire_ts" ] 2>/dev/null; then
            return 1
        fi
    fi
    
    # 写入到期时间戳（当前时间 + TTL）
    echo "$(( $(date +%s) + DEDUP_TTL ))" > "$cache_file"
    
    # 概率性清理过期缓存（每约 10 次触发执行一次，使用 Python clean-dedup 避免 find -exec bash 子进程爆炸）
    if [ $((RANDOM % 10)) -eq 0 ]; then
        python3 "$TOOL" clean-dedup "$DEDUP_DIR" "$DEDUP_TTL" &>/dev/null &
    fi
    
    return 0
}

# 写入 PID
echo $$ > "$PID_FILE"

# 统一日志函数
log() {
    local level="${1:-INFO}"
    shift
    # launchd 管理下 stdout 已被重定向到 launchd_watcher.stdout.log
    # 只写日志文件，避免 tee 双写产生冗余
    echo "[$(date '+%Y-%m-%d %H:%M:%S')][watcher][$level] $*" >> "$LOG_FILE"
}

# 心跳函数
heartbeat() {
    while true; do
        echo "$(date '+%Y-%m-%dT%H:%M:%S%z')" > "$HEARTBEAT_FILE"
        sleep 60
    done
}

# 清理函数
cleanup() {
    log INFO "文件监听器收到停止信号"
    # 杀掉所有子进程
    jobs -p | xargs -r kill 2>/dev/null
    rm -f "$PID_FILE" "$HEARTBEAT_FILE"
    log INFO "文件监听器已停止"
    exit 0
}
trap cleanup SIGINT SIGTERM

# 检查 fswatch
if ! command -v fswatch &> /dev/null; then
    log ERROR "fswatch 未安装，尝试安装..."
    if command -v brew &> /dev/null; then
        brew install fswatch 2>&1 | tee -a "$LOG_FILE"
        if [ $? -ne 0 ]; then
            log CRITICAL "fswatch 安装失败，退出"
            exit 1
        fi
        log INFO "fswatch 安装完成"
    else
        log CRITICAL "无法安装 fswatch，请手动: brew install fswatch"
        exit 1
    fi
fi

log INFO "============================================"
log INFO "Marvis-WorkBuddy Bridge 文件监听器 v3 启动"
log INFO "监听目录: $BRIDGE_DIR/status/workbuddy_pending/"
log INFO "心跳间隔: 60s | 重拉机制: 启用"
log INFO "PID: $$"
log INFO "============================================"

# 启动心跳后台
heartbeat &
HEARTBEAT_PID=$!
log INFO "心跳进程已启动 (PID: $HEARTBEAT_PID)"

# ====== fswatch 存活监控 + 自动重拉循环 ======
MAX_RESTARTS=10
RESTART_COUNT=0
RESTART_WINDOW=300  # 5分钟内重试次数窗口
RESTART_WINDOW_START=$(date +%s)

run_fswatch() {
    # 在 pipe subshell 中确保 PATH 完整（Marvis 受限环境有时丢失系统 bin）
    export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
    # v3 加固：latency 聚合 + 事件去抖 + 溢出保护 + 临时文件过滤
    # 注意：不使用 --event-flags（path+flags 合并为同一字段，导致 *.json 过滤失败）
    fswatch -0 \
        --latency 2 \
        --event Created \
        --event Updated \
        --event Renamed \
        --exclude '.*\.tmp$' \
        --exclude '.*\.swp$' \
        --exclude '.*\.swx$' \
        --exclude '\.DS_Store' \
        --exclude '.*~$' \
        --allow-overflow \
        "$BRIDGE_DIR/status/workbuddy_pending/"
}

while true; do
    log INFO "启动 fswatch 子进程 (第 $((RESTART_COUNT + 1)) 次)"

    # 重试窗口管理：超过5分钟重置计数器
    now=$(date +%s)
    if [ $((now - RESTART_WINDOW_START)) -gt $RESTART_WINDOW ]; then
        RESTART_COUNT=0
        RESTART_WINDOW_START=$now
    fi

    if [ $RESTART_COUNT -ge $MAX_RESTARTS ]; then
        log CRITICAL "fswatch 在 ${RESTART_WINDOW}s 内重试已达上限 ($MAX_RESTARTS)，退出监听"
        echo "{\"status\": \"dead\", \"reason\": \"max_restarts\", \"last_seen\": \"$(date '+%Y-%m-%dT%H:%M:%S%z')\"}" > "$HEARTBEAT_FILE"
        cleanup
        exit 1
    fi

    # 使用进程替代代替管道，避免子 shell 变量隔离导致 RESTART_COUNT 重置不生效
    # 之前: run_fswatch | while read ... (管道右侧在子 shell 中，变量修改丢弃)
    # 现在: while read ... < <(run_fswatch) (while 循环在父 shell 中，变量修改生效)
    while read -d "" event_path; do
        # 重置重试计数器（fswatch 正常产出数据说明活着）
        RESTART_COUNT=0

        # 过滤非 JSON 文件
        [[ "$event_path" != *.json ]] && continue
        # 跳过模板文件
        [[ "$(basename "$event_path")" == "template.json" ]] && continue
        # 跳过临时/隐藏文件
        [[ "$(basename "$event_path")" == .* ]] && continue

        # 文件级去重：同一路径 300 秒内只触发一次（消除 fswatch 事件风暴）
        if ! dedup_check "$event_path"; then
            # 跳过去重文件，不写日志（生产环境日志量已经够大）
            continue
        fi

        timestamp=$(date '+%Y-%m-%d %H:%M:%S')
        project=$(python3 "$TOOL" get-task-field "$event_path" project unknown 2>/dev/null)

        log INFO "检测到新任务: $event_path (项目: $project)"

        # 校验任务格式
        VALIDATOR="$BRIDGE_DIR/scripts/task_validator.py"
        if [ -f "$VALIDATOR" ]; then
            if python3 "$VALIDATOR" "$event_path" 2>/dev/null; then
                # 写入触发队列（每个任务独立文件，避免并发覆盖丢失）
                mkdir -p "$TRIGGER_DIR"
                task_id=$(basename "$event_path" .json)
                trigger_file="$TRIGGER_DIR/$(date +%s%N)_${task_id}.json"
                echo "{\"timestamp\": \"$timestamp\", \"task_file\": \"$event_path\", \"project\": \"$project\", \"status\": \"valid\"}" > "$trigger_file"
                log INFO "任务校验通过，已写入触发队列"

                # 检查是否有 trigger_next 事件驱动（安全方式：用 python 脚本参数传递）
                trigger_next=$(python3 "$TOOL" get-task-field "$event_path" trigger_next "" 2>/dev/null)
                if [ -n "$trigger_next" ]; then
                    log INFO "事件驱动触发: trigger_next=$trigger_next"
                fi
            else
                log WARN "任务校验失败，已跳过: $(basename "$event_path")"
            fi
        else
            log WARN "校验脚本不存在，直接触发"
            mkdir -p "$TRIGGER_DIR"
            task_id=$(basename "$event_path" .json)
            trigger_file="$TRIGGER_DIR/$(date +%s%N)_${task_id}.json"
            echo "{\"timestamp\": \"$timestamp\", \"task_file\": \"$event_path\", \"project\": \"$project\", \"status\": \"unchecked\"}" > "$trigger_file"
        fi
    done < <(run_fswatch)

    # fswatch 进程退出了
    RESTART_COUNT=$((RESTART_COUNT + 1))
    log WARN "fswatch 进程退出 (第 $RESTART_COUNT 次)，3秒后重拉..."

    echo "{\"status\": \"restarting\", \"restart_count\": $RESTART_COUNT, \"last_seen\": \"$(date '+%Y-%m-%dT%H:%M:%S%z')\"}" > "$HEARTBEAT_FILE"

    sleep 3
done
