# ⛔ 本项目已于 2026-10-12 下线（Decommissioned）

> MarvisBridge（本地真身：`/Volumes/ZHITAI/WorkBuddy/marvis_bridge`，入口软链 `~/workbuddy_marvis_bridge`）
> 自 **2026-10-12** 起**停止运行**。GitHub 仓库已 archive。本文件是最终状态说明。
> **除非读完本文并得到用户明确同意，不要重新启用任何部件。**

## 为什么下线

- 生产端（Marvis 应用）自 2026-08-14 起零任务；
- 全线停摆 4 个月**零用户可见影响** ⇒ 揭示价值约等于 0；能力已被现役系统替代（Claw 的行情/财报/巡检、系统 memwatch）；
- 维护税反复支付：PID 锁停摆（6–8 月）/ launchd 78 循环 / **262MB 错误邮件仓**（两个 cron 每分钟失败、持续 4 个月无人察觉）。

## 已停用（2026-10-12，全部可回滚）

| 部件 | 处置 | 恢复方式 |
|---|---|---|
| launchd：`com.marvis-bridge.monitor` / `.watcher` / `com.workbuddy.poller` | bootout + **disable** | `launchctl enable gui/$UID/<label>` + `launchctl bootstrap gui/$UID ~/Library/LaunchAgents/<label>.plist` |
| cron：`feishu_qa_bot_watchdog` / `status_aggregator` | 注释（原命令保留在注释内，含日期与原因） | 取消注释 |
| WorkBuddy 自动化：「🔗【桥接】Marvis 任务消费」「🔎 首跑核验」 | 已删除 | 如需重建，参照 Claw 巡检账本 PA-020/PA-021 的历史记录 |
| 运行态数据（tasks / results / done / status / logs 等） | 归档 `.../WorkBuddy/_archive/MarvisBridge-runtime-20261012.tar.gz`（292 个文件，逐项核对一致；**原目录保留冻结**） | 解档即得 |

## 保留

- 本仓库（代码 + 历史）与本地检出（冻结）；
- Marvis 应用本体（用户资产，未触碰）。
- ⚠️ 本工作树含**未跟踪的运行态残留**（`claw/done`、`claw/results` 下的 32 个文件，来自 2026-10-12 最后一次运行）——已随归档备份，**不要再提交**。

## 复活方法（如确需，须用户明确同意）

1. `gh repo unarchive guandada123/MarvisBridge`
2. 取消两条 cron 注释
3. `launchctl enable` + `bootstrap` 三个 plist
4. 按需重建 WorkBuddy 消费端自动化
5. 需要历史数据时从 `_archive` 解档

## 记录

- Claw 巡检账本：**PA-020**（首跑核验，4/4 达成）、**PA-021**（退役全记录）。
- Learnings：`2026-10-12`（cron/launchd 僵尸清理 + 退役三条硬动作：停 cron 注释留因 / 停 launchd bootout+disable / mail spool 是静默失败的出口）。
