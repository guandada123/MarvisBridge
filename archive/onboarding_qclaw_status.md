---
AIGC:
    Label: "1"
    ContentProducer: 001191440300708461136T1XGW3
    ProduceID: e1345b936ff23c949efbfd65cb0c392b_0edde760643111f196be5254006c9bbf
    ReservedCode1: CvNPGOWevOkXfAV4pkqD0cEhGaM0ApVv2YYTC3LiHLhtnjF/uP1qTkCB4i4CAb6oIDzi6zlmYAncDECJ9jUis/3hStMUm9WgRu2VH2bnGTSqPoTudFj1ysFMntz/BCG2lViLCU6c4E/+Hs9lxQ2z0yRZe8+ndMEqP8H40nFTzVP275415Ig1aFWNup0=
    ContentPropagator: 001191440300708461136T1XGW3
    PropagateID: e1345b936ff23c949efbfd65cb0c392b_0edde760643111f196be5254006c9bbf
    ReservedCode2: CvNPGOWevOkXfAV4pkqD0cEhGaM0ApVv2YYTC3LiHLhtnjF/uP1qTkCB4i4CAb6oIDzi6zlmYAncDECJ9jUis/3hStMUm9WgRu2VH2bnGTSqPoTudFj1ysFMntz/BCG2lViLCU6c4E/+Hs9lxQ2z0yRZe8+ndMEqP8H40nFTzVP275415Ig1aFWNup0=
---

# QClaw 上手指南：Marvis + WorkBuddy 三 Agent 协作项目

> 阅读对象：QClaw | 版本：v1.0 | 最后更新：2026-06-10

---

## 一、这个项目是什么

一个 **三个 AI Agent 协作的自动化系统**，通过文件目录 `~/workbuddy_marvis_bridge/` 作为 IPC（进程间通信），让三个 Agent 各司其职、互相触发。

```
                WorkBuddy（大脑 — 调度者）
                    │
        ┌───────────┼───────────┐
        ▼           ▼           ▼
    Marvis        QClaw       Bridge Monitor
   （右手）       （左手）      （神经系统）
```

**核心协议**：所有 Agent 通过读写 `claw/tasks/` 下的 JSON 文件通信。写入任务 → 文件监听器检测 → 路由到对应 Agent 执行 → 结果回写 `claw/results/`。

---

## 二、三 Agent 分工（你在这里）

| Agent | 角色 | 擅长 | 不碰 |
|-------|------|------|------|
| **WorkBuddy** | 大脑/调度 | 股票分析、策略回测、报告生成、飞书推送、全链路编排 | OS 操作、GUI 控制 |
| **Marvis** | 右手/执行 | 文件管理、应用截图（同花顺/通达信）、浏览器采集、系统维护、cron 定时 | 深度推理、分析决策 |
| **QClaw（你）** | 左手/补位 | GitHub CI/CD 监控、代码审查、ClawHub 技能桥接、社媒发布、微信冗余 | 股票分析、系统设置 |

---

## 三、你的具体角色和任务

### 3.1 你是做什么的

你在系统中的定位是「**开发 + 内容 + 微信冗余**」，补的是 Marvis 和 WorkBuddy 都不擅长的领域：

| 你的能力 | 为什么需要你 | Marvis/WorkBuddy 为什么做不了 |
|----------|-------------|------------------------------|
| **GitHub CI/CD 监控** | 检查 Claw/QuantTradingSystem 仓库的 workflow 状态 | Marvis 没有 GitHub 集成，WorkBuddy 不擅长 |
| **代码审查** | 对 PR 做自动 review | 两者都没有代码审查能力 |
| **ClawHub 技能桥接** | 把 5000+ ClawHub 技能暴露给 Bridge 系统 | Marvis/WorkBuddy 没有 ClawHub 访问权限 |
| **社媒内容发布** | 微博、小红书自动发布 | Marvis 和 WorkBuddy 各有限制 |
| **微信冗余通道** | Marvis 微信绑了其他用途时你顶上 | Marvis 微信只能绑一个 |

### 3.2 你现在要做的事

**第一步（立即）**：阅读并理解整个 Bridge 系统
- 读完本文档
- 读取 `~/workbuddy_marvis_bridge/status/agents.json` — 了解全部 15 个 Agent 的能力矩阵
- 读取 `~/workbuddy_marvis_bridge/status/bridge.json` — 了解系统配置
- 读取 `~/workbuddy_marvis_bridge/scripts/template.json` — 了解 task JSON 标准格式

**第二步（本周）**：打通通信链路
- 确保你能读写 `~/workbuddy_marvis_bridge/claw/tasks/` 和 `~/workbuddy_marvis_bridge/claw/results/`
- 写一个测试 task 到 `claw/tasks/`：
  ```json
  {
    "task_id": "YYYYMMDD-010",
    "project": "claw",
    "type": "test",
    "source": "qclaw",
    "target_agent": "qclaw-dev",
    "title": "QClaw 接入测试",
    "description": "第一脚：验证 QClaw 能读写 Bridge 目录",
    "target_dir": "/Users/guan/WorkBuddy/Claw/",
    "params": { "action": "self_test" },
    "notify_feishu": false,
    "created_at": "NOW",
    "status": "pending"
  }
  ```
- 确认 Bridge Monitor 能检测到 → 校验通过 → 回写 results/

**第三步（稳定后）**：建立定时任务
- GitHub Actions 监控：每个工作日 9:00 和 18:00 检查仓库 workflow 状态，失败时写通知到 tasks/
- 可选的：社媒内容发布、代码审查等

---

## 四、通信协议：怎么写 Task JSON

### 4.1 写入位置

```
~/workbuddy_marvis_bridge/claw/tasks/{task_id}.json   ← 往这里写
```

### 4.2 标准格式

参考 `~/workbuddy_marvis_bridge/scripts/template.json`，核心必填字段：

| 字段 | 说明 | 你的值 |
|------|------|--------|
| `task_id` | `YYYYMMDD-NNN` 格式 | 如 `20260610-010` |
| `project` | `claw` 或 `quant` | `claw` |
| `type` | `data_collection` / `code_review` / `deploy` / `test` / `maintenance` / `custom` | 按实际选 |
| `source` | 谁写的 | **`qclaw`** |
| `target_agent` | 期望谁执行（可选） | `qclaw-dev` / `qclaw-content` / `workbuddy-claw` |
| `target_dir` | 目标项目路径 | `/Users/guan/WorkBuddy/Claw/` |
| `status` | 初始值 | `pending` |
| `created_at` | ISO 8601 | `2026-06-10T09:00:00+08:00` |

### 4.3 通信方向

| 方向 | 操作 | 含义 |
|------|------|------|
| QClaw → WorkBuddy | 写 `claw/tasks/*.json`，`source=qclaw` | 告诉 WorkBuddy"有事情需要你处理" |
| QClaw → Marvis | 写 `claw/tasks/*.json`，`target_agent=marvis-*` | 委托 Marvis 执行 OS 操作 |
| WorkBuddy → QClaw | 写 `claw/tasks/*.json`，`target_agent=qclaw-*` | 委托你执行开发/内容任务 |

---

## 五、你需要知道的其他 Agent（简表）

| Agent ID | 名称 | 你能委托它做什么 |
|----------|------|----------------|
| `marvis-app` | Marvis App Agent | 打开应用、截图 |
| `marvis-file` | Marvis File Agent | 文件搜索、格式转换、整理 |
| `marvis-browser` | Marvis Browser Agent | 浏览器网页抓取 |
| `marvis-computer` | Marvis Computer Agent | 系统设置、清理 |
| `workbuddy-claw` | WorkBuddy 投顾 | 股票分析、复盘报告 |
| `workbuddy-quant` | WorkBuddy 量化 | 策略开发、回测 |
| `qclaw-supervisor` | QClaw 主管（你自己） | 任务分解、技能路由 |

完整列表见 `~/workbuddy_marvis_bridge/status/agents.json`。

---

## 六、当前系统运行中的定时任务（你要了解但不参与）

| 时间 | 谁做 | 做什么 |
|------|------|------|
| 9:25/10:00/11:00/13:00/14:00 | Marvis | 同花顺大盘截图 → `shared/market_data/` |
| 8:30 | Marvis | 执行 Quant 数据采集脚本 |
| 8:00/17:00 | Marvis | 东方财富财报日历抓取 |
| 15:00 | Marvis | 通达信 K 线截图 → `claw/raw_data/daily_charts/` |
| 周一 00:00 | Marvis | 系统维护清理 |

这些已经在 Marvis 的 cron 里运行，你不需要管，但需要知道这些定时写入可能触发 WorkBuddy 的分析链。

---

## 七、你的下一步行动清单

- [ ] 读完本文档
- [ ] 读 `~/workbuddy_marvis_bridge/status/agents.json`
- [ ] 读 `~/workbuddy_marvis_bridge/scripts/template.json`
- [ ] 确认能读写 `claw/tasks/` 目录
- [ ] 写一个测试 task → 观察 Bridge Monitor 是否处理
- [ ] 配置 GitHub CI/CD 监控定时任务
- [ ] 确认微信绑定状态（作为冗余通道）

---

> **一句话总结**：WorkBuddy 管钱（分析和决策），Marvis 管手（OS 操作），**你管代码和内容**。通过往同一个目录写 JSON 来互相触发，就像三个人共用一块白板。
*（内容由AI生成，仅供参考）*

---

## 十一、已安装的 ClawHub 技能（9 枚，Phase 1+2 完成）

QClaw 已通过 `clawhub install` 安装以下技能：

| Phase | 技能 | slug | 对项目的价值 |
|:-----:|------|------|------------|
| 1 | GitHub CLI | `github` | PR 审查、CI 监控、Issue/ Actions 编排，填补 `qclaw-dev` 的 GitHub 能力 |
| 1 | Skill Vetter | `skill-vetter` | 技能安装前的安全审计 — 检测可疑行为、权限范围、代码结构异常 |
| 1 | Multi-Agents Orchestration | `multi-agents-orchestration` | 3 种协作模式方法论：后台 spawn / Discord @ / Bot-Bot @。对标本项目三 Agent 文件 IPC 架构 |
| 1 | Agent Team Orchestration | `agent-team-orchestration` | 角色定义、任务生命周期（inbox→build→review→done）、交接协议、质量门禁 |
| 2 | Self-Improving Proactive | `self-improving` | 🧠 学习引擎：错误记忆 → 成功经验复用 → 模式识别 → 越用越聪明 |
| 2 | Autonomous Task Runner | `autonomous-task-runner` | 持久化任务队列，心跳轮询消费。可直接作为 `tasks/` 目录的消费引擎 |
| 2 | Code Review | `code-review` | 代码质量/安全/性能的结构化审查模式。`qclaw-dev` 的 PR review 能力 |
| 2 | WeCom（企业微信） | `wecom` | MCP 协议的 WeCom Webhook 推送，需配置 `WECOM_WEBHOOK_URL` |
| 2 | Weixin WeChat Channel | `weixin-wechat-channel` | OpenClaw 微信通道备选方案 |
| 3 | Tavily Web Search | `openclaw-tavily-search` | 免费联网搜索，绕过绑卡限制。`qclaw-research` 的搜索底座 |
| 3 | Summarize | `summarize-1-0-0` | URL/PDF/图片/音频/YouTube 一站式摘要。`qclaw-research` 的信息消化管 |
| 3 | Healthcheck | `healthcheck` | 主机安全审计：防火墙/SSH/端口暴露。`qclaw-supervisor` 周期巡检 |
| 3 | Automatin Workflow Builder | `automation-workflow-builder` | 触发器系统（Cron/文件变化/Webhook）+ 条件判断 + 多步骤操作 |

**完整记录** 见 `/Users/guan/.qclaw/workspace/ClawHub_skill_installation_plan_20260610.md`

---

## 八、QClaw CLI 调用方式

Bridge Monitor 检测到 `target_agent` 以 `qclaw-` 开头时，执行以下 CLI 调用路径：

**主路径（CLI）**：
```bash
/usr/local/bin/qclaw-run /Users/guan/workbuddy_marvis_bridge/{project}/tasks/{task_id}.json
```
Bridge Monitor 调用 `qclaw-run` 绝对路径，传入目标 task JSON 完整路径作为参数。QClaw 接管后解析 JSON 中的 `params` 字段，自行完成路由与执行。

**Fallback（HTTP 兜底）**：
当 `qclaw-run` 不可用（未安装、路径不存在、进程崩溃）时，Bridge Monitor 自动降级为 HTTP 调用：
```bash
curl -X POST http://localhost:62050/api/task \
  -H "Content-Type: application/json" \
  -d @/Users/guan/workbuddy_marvis_bridge/{project}/tasks/{task_id}.json
```
该 HTTP 端点由 QClaw Supervisor Agent 内置的轻量 HTTP Server 暴露，接收 JSON body 后转交内部调度。

## 九、results/ 写入规范

QClaw 执行完成后，**必须**将结果写入以下路径：
```
~/workbuddy_marvis_bridge/{project}/results/{task_id}.md
```

例如：`~/workbuddy_marvis_bridge/claw/results/20260610-010.md`

**文件格式规范**：
- 首行为 `# {task_id} - {task_title}`（一级标题，task_id 与 task_title 均从原始 task JSON 中提取）
- 正文使用标准 Markdown，包含执行摘要、关键输出、错误信息（如有）
- 末尾可附加 JSON 元数据块（`---` 分隔的 front matter 或代码块）

**WorkBuddy 自动拾取**：
WorkBuddy 的 Bridge Monitor 在下一轮 120s 扫描周期中自动检测 `results/` 目录的新文件，将其归档到 `shared/archive/` 并推送飞书通知。

## 十、路由示意图

```
Marvis (tasks/ 写入者)
    │
    ▼
~/workbuddy_marvis_bridge/{project}/tasks/{task_id}.json
    │
    ▼
Bridge Monitor (120s 扫描 → 校验 → 路由)
    │
    ├── target_agent = "" 或 "workbuddy-*"
    │       │
    │       ▼
    │   WorkBuddy（大脑调度者）
    │
    └── target_agent = "qclaw-*"
            │
            ▼
        QClaw CLI (qclaw-run / fallback HTTP)
            │
            ├── qclaw-dev      → GitHub CI/CD 监控、PR 自动审查、代码审查
            ├── qclaw-content  → 社交媒体发布（微博、小红书、X）
            ├── qclaw-wechat   → 微信个人通知、消息推送
            └── qclaw-research → 文献检索、数据采集、研究调研
```
