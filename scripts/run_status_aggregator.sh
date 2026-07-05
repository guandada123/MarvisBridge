#!/bin/bash
# 四项目统一状态巡检 - launchd 封装脚本
# 每天 08:00 执行，异常时推送飞书

export PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
cd ~/workbuddy_marvis_bridge

# 执行状态汇总检查
REPORT=$(/Users/guan/.workbuddy/binaries/python/versions/3.13.12/bin/python3 scripts/status_aggregator.py --alert 2>&1)
EXIT_CODE=$?

# 如果有异常（退出码非0），推送飞书告警
if [ $EXIT_CODE -ne 0 ]; then
    ~/.workbuddy/binaries/node/cli-connector-packages/bin/lark-cli im +messages-send \
      --chat-id oc_9ee5303497f5e0e71666b610d6bdc346 \
      --as bot \
      --markdown "🚨 四项目状态巡检异常\n━━━━━━━━━━━━━\n$REPORT\n━━━━━━━━━━━━━" 2>&1
fi

echo "$(date): status aggregator executed, exit code $EXIT_CODE" >> ~/.workbuddy/logs/launchd.log
exit $EXIT_CODE
