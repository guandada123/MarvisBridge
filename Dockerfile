# ============================================================
# Marvis Bridge — Dockerfile v1.0
# 基于 Alpine Python 3，运行 bridge 守护进程
# ============================================================
FROM python:3.12-alpine

LABEL org.marvis.bridge="task-bridge"
LABEL version="1.0"

# 系统依赖（基础工具）
RUN apk add --no-cache \
    bash \
    curl \
    jq \
    tzdata && \
    cp /usr/share/zoneinfo/Asia/Shanghai /etc/localtime && \
    echo "Asia/Shanghai" > /etc/timezone

# 创建非 root 用户
RUN addgroup -g 1000 bridge && \
    adduser -D -u 1000 -G bridge bridge

# 工作目录
WORKDIR /home/bridge/workbuddy_marvis_bridge

# 按层复制（先复制不常变的配置和脚本）
COPY --chown=bridge:bridge shared/ shared/
COPY --chown=bridge:bridge scripts/ scripts/
COPY --chown=bridge:bridge bridge/ bridge/
COPY --chown=bridge:bridge docs/ docs/

# 创建运行时目录
RUN mkdir -p logs status/trigger_queue status/workbuddy_pending \
    status/locks status/signals status/dead_letter_archive \
    claw/tasks claw/done claw/dead_letter claw/results claw/raw_data \
    quant/tasks quant/done quant/dead_letter quant/results quant/raw_data && \
    chown -R bridge:bridge .

# 切换到非 root
USER bridge

# 健康检查
HEALTHCHECK --interval=60s --timeout=10s --retries=3 \
    CMD ./scripts/health_check.sh --quiet || exit 1

# 默认启动 monitor（主消费进程）
CMD ["bash", "scripts/bridge_monitor.sh"]
