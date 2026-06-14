# ⚠️ Marvis 任务输出目录 — 请阅读

**正确路径：** 请将任务写入 `status/workbuddy_pending/{task_id}.json`

**当前路径：** 你正在写入 `claw/tasks/` — 这是错误的目录

**后果：** WorkBuddy 轮询 `status/workbuddy_pending/`，无法发现此目录的任务

**补偿机制：** `scripts/task_sync.sh` 会定期将任务移动到正确目录

**文档参考：** 见 `shared/ROADMAP.md` 第161行：
```
写入路径: ~/workbuddy_marvis_bridge/status/workbuddy_pending/{task_id}.json
```

请立即修正输出目录为 `status/workbuddy_pending/`
