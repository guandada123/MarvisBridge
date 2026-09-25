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
