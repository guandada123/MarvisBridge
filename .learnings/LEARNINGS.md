# Learnings (marvis_bridge)

Corrections, insights, and knowledge gaps captured during development.

**Categories**: correction | insight | best_practice | knowledge_gap

---

### 2026-08-22 Marvis 应用 Beacon SDK 崩溃排查（含僵尸 launchd 清理）
- **类型**: insight
- **现象**: 用户报"近期系统又崩了"。Mac 崩溃报告 `~/Library/Logs/DiagnosticReports/Marvis-2026-08-22-204117.ips`：SIGABRT，崩溃栈 `beacon_napi.node → BeaconSdkLog → std::mutex::lock() 抛 system_error`。
- **根因**: 腾讯 Marvis 内置 Beacon 打点 SDK 的 mutex 锁异常（应用自身 bug）。诱因为 20:40 前后 Marvis 持续"用户未登录，清除 store"，Beacon 上报线程在异常状态下崩溃。**非 WorkBuddy 系统故障**——代理 9999、daemon-app-server、sidecar、外挂盘、内存全部正常，WindowServer 未复发（近10天无崩溃报告）。
- **处置**: Marvis 已由 launchd KeepAlive 自动重启（21:22），未再崩溃，无需人工干预。顺带清理僵尸服务：`com.marvis-bridge.monitor` / `com.marvis-bridge.watcher` 退出码 78（`bridge_monitor.sh` 权限 `-rw-------` 无执行位，手动跑 exit=126），项目已休眠但 launchd KeepAlive 反复拉起失败 → `launchctl bootout gui/$(id -u)/com.marvis-bridge.monitor|watcher` 卸载（plist 保留，可恢复）。
- **防复犯**: ① "系统崩了"先看 DiagnosticReports 最新 .ips 实锤是哪个进程，再排查，禁脑补；② 休眠项目的 launchd 服务应 bootout 而非留 KeepAlive 空转；③ Marvis 未登录状态是 Beacon SDK 崩溃诱因，若再崩先让用户重新登录 Marvis。
- **去重**: 首次

---

### 2026-10-12 桥接相关 cron/launchd 僵尸清理：发现 262MB 错误邮件仓（4 个月无人察觉）
- **类型**: correction
- **现象**: `/var/mail/guan` 积 **262MB / 约 35.6 万封**（2026-03-22 起），其中两个条目**每分钟各失败一封**持续 4 个月：① `~/openclaw_watchdog.sh` 18.7 万封（`openclaw: command not found`）；② 本仓 `scripts/feishu_qa_bot_watchdog.sh` 17 万封（`Operation not permitted`）。用户侧无任何感知。
- **根因**: ① openclaw 二进制已不存在（工具已卸载），watchdog 每分钟空踢；② QA bot 死于 7-03（lark-cli 丢失），其 watchdog 自 ~6-16 起被系统拒绝执行（文件权限 755、卷无 noexec、交互执行均正常 ⇒ 属 cron 进程对**外置盘/符号链路径**的特权限制；未逐层到底，留档）。
- **处置**: 两条 cron 注释（**原因与原命令保留在注释内**，可取消注释回滚）；launchd 三个僵尸（`com.marvis-bridge.monitor` / `.watcher` / `com.workbuddy.poller`）**bootout + disable 双动作**；262MB 邮件归档至 `_archive/cron-mail-spool-20261012.mbox`（cmp 校验）后清空，停止增长已实证（跨分钟边界 +0B）。
- **防复犯**: ① **launchd 退役必须 bootout + disable 双动作** —— 仅 bootout 会在重启/重登录后复活（8-22 条目只做了 bootout，本次发现三个僵尸又全回来了）；② 停用 cron **必须注释并留原因**（直接删除=无法回滚且无人知为何）；③ **本地 mail spool 是"静默失败最后会说话的地方"**——cron 错误不看≠没有，定期看一眼；④ 每分钟级 watchdog 仅当"被看护对象真的重要且命令真的存在"时才允许存在。
- **去重**: 与 2026-08-22「僵尸 launchd 清理」同族（本条修正其"仅 bootout"的做法）。
