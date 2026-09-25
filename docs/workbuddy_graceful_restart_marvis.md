# Marvis 接入说明 — WorkBuddy 内存自愈重启（不丢 UI）

> 2026-08-13 生成 | 脚本已就绪：`~/.local/bin/workbuddy_graceful_restart.sh`

## 目标
Marvis 负责**检测** WorkBuddy 内存压力，命中后调用重启脚本。重启走**正常关闭流程**（AppleScript quit → 等主进程退出 → renderer flush → open），**不丢 UI 历史对话**。

## 一、Marvis 侧检测任务配置

在 Marvis 界面新建一个定时检测任务（建议每 **5 分钟**一次），检测逻辑：

```bash
# ① 整机可用内存 < 512MB（free+inactive+speculative+purgeable）
SYS_AVAIL_MB=$(vm_stat | awk '/Pages free/{f=$3}/Pages inactive/{i=$3}/Pages speculative/{s=$3}/Pages purgeable/{p=$3} END{gsub(/\./,"",f);gsub(/\./,"",i);gsub(/\./,"",s);gsub(/\./,"",p);print (f+i+s+p)*$(sysctl -n hw.pagesize)/1048576}')
# ② WB 进程树总内存 > 8500MB
WB_MB=$(ps -axo rss=,command= | awk '/WorkBuddy\.app/ && !/watch_workbuddy_mem/ && !/sidecar-entry/ && !/daemon-app-server-entry/ && !/--serve/ {t+=$1} END{print int(t/1024)}')
```

**命中条件**（满足任一）：
- `SYS_AVAIL_MB < 512` 且 `WB_MB > 800`
- `WB_MB > 8500`

**命中后执行**：

```bash
~/.local/bin/workbuddy_graceful_restart.sh --reason "Marvis检测: 内存不足"
```

## 二、脚本行为（已验证）

| 步骤 | 动作 | 时间 |
|---|---|---|
| 0 | 前置检查 WB 主进程是否在运行，未运行直接拉起 | - |
| 1 | 备份 `~/.workbuddy/app/sessions.json` → `.bak` | - |
| 2 | `AppleScript quit` 走正常关闭流程 | ≤90s |
| 3 | 等主进程退出后给 renderer **15s flush 窗口**（IndexedDB/WAL） | 15s |
| 4 | 清理残留进程（**排除 sidecar/daemon/--serve 对话载体**，绝不 KILL） | ≤10s |
| 5 | `open` 重启 + 回读验证新主进程 | 12s |
| 6 | 自检会话数，为空自动从备份恢复 | 15s |

## 三、双保险
- 原 memwatch 常驻守护（launchd `com.workbuddy.memwatch`）仍在运行，马维斯漏检时兜底
- 两者共享同一配置源 `~/.local/etc/workbuddy_memwatch.conf`，参数一致不冲突

## 四、验证方式
```bash
# dry-run（只打印不执行）
~/.local/bin/workbuddy_graceful_restart.sh --dry-run --reason "测试"

# 日志
tail -f ~/Library/Logs/workbuddy_memwatch.log
```

## 五、阈值调整
改 `~/.local/etc/workbuddy_memwatch.conf` 后**重启 memwatch**（或让巡检中枢 bump）即可，Marvis 检测侧如用独立阈值则同步修改。
