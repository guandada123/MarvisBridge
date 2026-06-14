---
AIGC:
    Label: "1"
    ContentProducer: 001191440300708461136T1XGW3
    ProduceID: e1345b936ff23c949efbfd65cb0c392b_0e31945664df11f1aaba5254006c9bbf
    ReservedCode1: f77UBI1CO3NYrMjvnMM0TFXp4zY9xhvp2fdP/0LZcC5hnWrudRlLPC/RHoraPLsgR+G3SiNJL0OItD+VJfzSVFN7URyvwGIQuDjYsASQZ3OPj8aMu+bV+j+DH4w+67B2ZcLJXXc7mKz2iPM3soY35tkPeqdW/zDZpl1jljLZZy48YAXtivY+fsiGt88=
    ContentPropagator: 001191440300708461136T1XGW3
    PropagateID: e1345b936ff23c949efbfd65cb0c392b_0e31945664df11f1aaba5254006c9bbf
    ReservedCode2: f77UBI1CO3NYrMjvnMM0TFXp4zY9xhvp2fdP/0LZcC5hnWrudRlLPC/RHoraPLsgR+G3SiNJL0OItD+VJfzSVFN7URyvwGIQuDjYsASQZ3OPj8aMu+bV+j+DH4w+67B2ZcLJXXc7mKz2iPM3soY35tkPeqdW/zDZpl1jljLZZy48YAXtivY+fsiGt88=
---

# Marvis-WorkBuddy Bridge

两 Agent（Marvis / WorkBuddy）协作调度中枢。Marvis 负责系统管理、开发运维、内容发布与信息检索 → Bridge 校验/路由/派发 → WorkBuddy 专注金融分析与决策。

## 架构

```
                        ┌─────────────────────┐
                        │      Marvis          │
                        │  (cron + 文件写入)    │
                        │ 系统管理 · 开发运维   │
                        │ 内容发布 · 信息检索   │
                        └──────────┬──────────┘
                                   │ 写入 claw/tasks/ · quant/tasks/
                                   ▼
┌──────────────────────────────────────────────────────────────┐
│                        Bridge 调度层                           │
│                                                              │
│  ┌──────────────┐    ┌───────────────┐    ┌───────────────┐  │
│  │ file_watcher  │───→│ task_validator │───→│ bridge_monitor│  │
│  │ (fswatch 监听) │    │ (幂等·熔断·校验)│    │ (30s 轮询派发) │  │
│  └──────────────┘    └───────┬───────┘    └───────┬───────┘  │
│                              │                     │          │
│                    dead_letter/              workbuddy_       │
│                    (校验/执行失败)            pending/         │
└──────────────────────────────────────────────────────────────┘
                                                  │
                                                  ▼
                                         ┌──────────────┐
                                         │  WorkBuddy    │
                                         │ Claw·Quant   │
                                         │ 金融分析决策   │
                                         └──────────────┘
```

## 目录结构

```
workbuddy_marvis_bridge/
├── claw/                          # A股投资辅助子系统
│   ├── tasks/          ← Marvis 写入（watcher 监听源）
│   ├── done/           ← 已完成归档（含幂等键去重）
│   ├── dead_letter/    ← 校验/执行失败死信
│   ├── raw_data/       ← 原始行情数据缓存
│   └── results/        ← 产出物 + MANIFEST.json
├── quant/                         # 量化交易子系统（同上结构）
├── shared/
│   └── config/
│       ├── config.json            # 主配置文件（唯一配置源）
│       └── trading_calendar.json  # A股交易日历
├── status/
│   ├── agents.json                # Agent 注册表 + 路由规则
│   ├── bridge.json                # Bridge 运行时状态快照
│   ├── circuit_breaker.json       # 熔断器持久化
│   ├── heartbeat                  # watcher 心跳时间戳
│   ├── monitor.pid / watcher.pid  # 进程 PID
│   ├── trigger_queue/             # 校验通过后的触发队列
│   ├── workbuddy_pending/         # WorkBuddy 待处理队列
│   └── locks/                     # 应用操作锁
├── logs/
│   ├── watcher.log / monitor.log / bridge.log
│   └── archive/                   # 日志轮转归档
├── scripts/
│   ├── file_watcher.sh            # fswatch 文件监听器（常驻）
│   ├── bridge_monitor.sh          # 任务消费派发器（常驻）
│   ├── task_validator.py          # 任务校验 + 幂等 + 熔断
│   ├── bridge_tools.py            # QClaw 路由 + 工具集
│   ├── health_check.sh            # 全链路健康检查
│   ├── log_rotate.sh              # 日志轮转
│   ├── dead_letter_cleanup.sh     # 死信清理
│   └── gen_manifest.py            # 结果清单生成
└── archive/                       # 历史文档归档
```

## 数据流

```
1. Marvis cron 写入 JSON 任务到 claw/tasks/ 或 quant/tasks/
2. file_watcher.sh (fswatch) 检测新文件 → task_validator.py
3. task_validator.py:
   a. 幂等去重（检查 done/ 目录中的 {project}:{type}:{date}:{business_id}）
   b. 熔断器检查（30min 窗口失败率 > 50% → 断路 30min）
   c. 格式校验（required_fields / valid_types / valid_sources）
   d. 通过 → status/trigger_queue/ 写入触发文件
   e. 失败 → 写入 dead_letter/
4. bridge_monitor.sh 每 30s 轮询 trigger_queue/:
   a. target_agent 以 "qclaw-" 开头 → bridge_tools.py qclaw-run
   b. 其他 → status/workbuddy_pending/ (WorkBuddy 自行轮询消费)
5. QClaw 执行完成 → 结果写入 claw/results/ 或 quant/results/
```

## 启停运维

### 启动

```bash
# 1. 启动 watcher（文件监听）
cd ~/workbuddy_marvis_bridge/scripts
nohup ./file_watcher.sh &

# 2. 启动 monitor（任务消费派发）
nohup ./bridge_monitor.sh &

# 3. 验证
./health_check.sh
```

### 停止

```bash
kill $(cat ~/workbuddy_marvis_bridge/status/watcher.pid)
kill $(cat ~/workbuddy_marvis_bridge/status/monitor.pid)
```

### 重启

```bash
kill $(cat ~/workbuddy_marvis_bridge/status/monitor.pid) 2>/dev/null
kill $(cat ~/workbuddy_marvis_bridge/status/watcher.pid) 2>/dev/null
sleep 2
cd ~/workbuddy_marvis_bridge/scripts
nohup ./file_watcher.sh &
nohup ./bridge_monitor.sh &
./health_check.sh
```

### 状态检查

```bash
# 全链路健康检查（人类可读）
./health_check.sh

# JSON 格式（供监控消费）
./health_check.sh --json

# 静默模式（脚本判断）
./health_check.sh --quiet && echo "全部正常" || echo "有异常"
```

## 推荐的 crontab 配置

```cron
# 每 2 小时全链路健康检查，异常时飞书通知
0 */2 * * * cd ~/workbuddy_marvis_bridge/scripts && ./health_check.sh --quiet || python3 -c "from bridge_tools import send_feishu_alert; send_feishu_alert('Bridge 健康检查异常')"

# 每天凌晨 2:00 日志轮转
0 2 * * * cd ~/workbuddy_marvis_bridge/scripts && ./log_rotate.sh

# 每天凌晨 3:00 死信清理（保留 30 天）
0 3 * * * cd ~/workbuddy_marvis_bridge/scripts && ./dead_letter_cleanup.sh

# 每天凌晨 4:00 数据滚动清理
0 4 * * * cd ~/workbuddy_marvis_bridge/scripts && python3 bridge_tools.py rotate

# 每小时生成结果清单
0 * * * * cd ~/workbuddy_marvis_bridge/scripts && python3 gen_manifest.py
```

## 故障恢复

| 症状 | 排查步骤 | 修复 |
|------|---------|------|
| watcher 不监听 | `./health_check.sh` → heartbeat > 180s？ | 重启 watcher |
| 任务堆积在 tasks/ | `ls claw/tasks/*.json \| wc -l` > 10 | 重启 watcher + monitor |
| 死信激增 | `ls claw/dead_letter/` | 检查 task_validator 日志，修正任务格式后手动重试 |
| QClaw 调用超时 | monitor.log 含 "TimeoutExpired" | 重启 QClaw，检查 openclaw.json 端口 |
| trigger_queue 积压 | > 20 条 | 检查 monitor 是否存活，增加消费频率 |
| workbuddy_pending 积压 | > 10 条 | 检查 WorkBuddy 是否在线 |

## 配置要点

- **唯一配置源**: `shared/config/config.json`
- **Agent 路由**: `status/agents.json`（修改后无需重启，下次读取生效）
- **熔断参数**: config.json → `circuit_breaker`（失败率阈值 / 断路时间 / 半开探针数）
- **幂等键格式**: `{project}:{type}:{date}:{business_id}`，检查 `done/` 目录去重
- **QClaw 端口**: 统一为 62050（agents.json 中 qclaw-supervisor.entry.port）

## 版本

v3.1 — 2026-06-10
*（内容由AI生成，仅供参考）*
