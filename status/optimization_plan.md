# Marvis 可接管任务清单与流程优化方案

> 基于全网调研 + 现有自动化清单 + 双项目结构交叉分析
> 生成时间：2026-06-10

---

## 一、Marvis 能做什么（WorkBuddy 做不了或做得不够好的）

| 能力 | Marvis 优势 | WorkBuddy 劣势 |
|------|------------|----------------|
| **操作系统级文件管理** | 语义搜索、格式批量转换、智能归档 | 只能通过 Shell 命令操作，缺乏语义理解 |
| **应用操控** | 直接控制 GUI 应用（同花顺/通达信/浏览器） | 无 GUI 操控能力 |
| **浏览器自动化** | 继承登录态、填表、多步导航 | 只能抓取公开网页 |
| **跨端远程** | 手机实时触控电脑桌面 | 微信消息驱动，单向 |
| **系统维护** | 清理缓存、管理启动项、磁盘监控 | 需要手动写脚本 |
| **隐私模式** | 端侧 Qwen 模型，断网可用 | 必须连接大模型 |

---

## 二、分模块接管方案

### 📈 模块 A：投顾操盘 — Marvis 可接管 2/7

| # | 现有自动化 | 当前由谁做 | Marvis 接管方案 | 收益 |
|---|-----------|-----------|----------------|------|
| 18 | 智能选股（9:00） | WorkBuddy | **不变** — 深度推理是 WorkBuddy 强项 | — |
| 19 | 每日复盘（15:30） | WorkBuddy | **增强** — Marvis 截取当日 K 线图 + 通达信导出数据 → raw_data/ → WorkBuddy 分析 | 数据更精准 |
| 20 | 每周总结（周五） | WorkBuddy | **不变** | — |
| 21-24 | 月/季/半年/年总结 | WorkBuddy | **不变** | — |

**具体任务模板**：

```json
// Marvis 写入 claw/tasks/
{
  "task_id": "20260610-002",
  "project": "claw",
  "type": "data_collection",
  "source": "marvis",
  "priority": "high",
  "title": "每日复盘-行情截图采集",
  "description": "收盘后打开通达信，截取持仓股日K线图、大盘指数分时图、板块涨幅排名，保存到 raw_data/",
  "params": {
    "app": "通达信",
    "screenshots": ["持仓股日K", "上证分时", "板块涨幅TOP10"],
    "output_dir": "claw/raw_data/daily_charts/",
    "filename_pattern": "{stock_code}_{date}.png"
  },
  "notify_feishu": true,
  "feishu_tag": "[Claw]",
  "created_at": "2026-06-10T15:30:00+08:00",
  "status": "pending"
}
```

---

### 📊 模块 B：炒股助理 — Marvis 可接管 4/7

| # | 现有自动化 | 当前方案 | Marvis 接管方案 | 收益 |
|---|-----------|---------|----------------|------|
| 1 | 盘中问答 | WorkBuddy 监控飞书 + WebSearch | **不变** — 对话型任务不适合 Marvis | — |
| 2 | 盘中监控（大盘快照） | WebSearch 获取指数 | **Marvis 接管** → 直接打开同花顺截图指数面板，写入 raw_data/ | 实时性更好，无需 API |
| 3 | 盘中持仓建议 | WorkBuddy Stock Skill | **增强** — Marvis 提供实时截图数据源 | 减少 API 依赖 |
| 7 | 财报预警 | WorkBuddy WebSearch | **Marvis 接管** → Browser Agent 定时抓取东方财富财报日历页 | 更可靠 |
| 10 | 微信文章早报 | wechat-article-fetcher | **Marvis 接管** → Browser Agent 打开搜狗微信搜索，批量采集 → raw_data/ | 绕过反爬 |
| 11 | 微信读书早报 | weread_fetch.py | **不变** — 已有成熟脚本 | — |

**接管后优化效果**：
- 每日减少 ~15 次 WorkBuddy API 调用（WebSearch → 本地截图替代）
- 盘中监控从"文本数值"升级为"视觉截图"，更直观
- 财报/文章采集不受反爬限制

---

### 🇺🇸 模块 C：美股监控 — Marvis 可接管 1/3

| # | 现有自动化 | Marvis 接管方案 |
|---|-----------|----------------|
| 15 | 盘前分析 | **增强** — Marvis 定时打开 Yahoo Finance/CNBC 截图 → raw_data/ |
| 16-17 | 盘中/收盘 | **不变** — 高频定时任务不适合 Browser Agent 效率 |

---

### 🔧 模块 D：系统维护 — Marvis 完全接管

| 现有自动化 | 方案 | Marvis 指令 |
|-----------|------|-----------|
| #25 定期梳理全局记忆 | WorkBuddy 读文件 | **Marvis 接管** → File Agent 扫描目录 + 生成报告 |

**新增 Marvis 专有任务**（WorkBuddy 做不到的）：

| 任务 | Marvis 定时指令 | 频率 |
|------|----------------|------|
| 项目缓存清理 | "清理 Claw/.workbuddy/ 下所有 __pycache__ 和 .pyc 文件" | 每周一 00:00 |
| 磁盘空间监控 | "检查磁盘剩余空间，低于 10% 时飞书通知" | 每天 01:00 |
| Git 备份检查 | "检查 Claw 和 QuantTradingSystem 的 git status，如有未提交变更通知我" | 每天 02:00 |
| 临时文件清理 | "清理下载文件夹中超过 30 天的文件，列出待删除清单让我确认" | 每两周一次 |

---

### 🧪 模块 E：QuantTradingSystem — Marvis 可接管 3 项

| 当前组件 | 状态 | Marvis 接管方案 | 收益 |
|---------|------|----------------|------|
| `scripts/fetch_data.py` | 手动运行 | **Marvis 接管** → 每天定时执行 python 脚本采集数据，验证结果后写标记 | 自动化零代码 |
| `ai-scheduler/health_monitor.py` | 5分钟循环 | **增强** — Marvis 补充系统级健康检查（CPU/内存/磁盘）→ raw_data/ | 监控更全面 |
| Docker 服务管理 | 手动 docker-compose | **Marvis 接管** → "每天早上 8 点启动 docker-compose，晚上 22 点停止" | 省电省资源 |
| GitHub Actions 监控 | 仅 CI 内部 | **Marvis 新增** → Browser Agent 检查最新 workflow run 状态，失败时飞书通知 | 故障感知 |

---

## 三、流程优化：端到端改造前后对比

### 3.1 每日复盘链路

**改造前（纯 WorkBuddy）**：
```
15:05 收盘回顾自动化触发
  → WebSearch 获取大盘数据
  → stock-realtime-quote 获取持仓价格
  → 生成文本报告
  → 推送到飞书
```

**改造后（Marvis + WorkBuddy）**：
```
15:00 Marvis 打开通达信/同花顺
  → 截屏持仓股日K线图 + 大盘分时图
  → 写入 ~/bridge/claw/raw_data/daily_charts/

15:05 Marvis 写入任务到 ~/bridge/claw/tasks/
  → "采集完成，请分析"

15:05-15:10 Bridge Monitor 检测到任务
  → WorkBuddy 读取截图 + API 数据
  → 综合生成含图表的复盘报告
  → 写入 ~/bridge/claw/results/
  → 飞书推送

15:10 Marvis 读取 results/ → 微信通知用户
```

**效果**：从"纯文本"→"图文并茂"，数据源从 API 扩展为 API + 真实截图交叉验证。

### 3.2 盘中监控链路

**改造前**：5 个独立自动化各自搜索 API，每小时调用 5 次。

**改造后**：
```
每个整点 Marvis 截取一张同花顺大盘面板
  → 一次截图包含：上证/深证/创业板 + 板块涨幅 + 北向资金

WorkBuddy 从一张图提取所有信息
  → 替代 5 个独立自动化
```

**效果**：每小时 API 调用从 5 次降到 1 次，信息更集中。

---

## 四、优先级矩阵

| 优先级 | 任务 | 投入 | 收益 | 理由 |
|:------:|------|:----:|:----:|------|
| **P0** | 每日复盘截图采集 | 低 | 高 | 立即可做，效果明显 |
| **P0** | 系统维护（清理/备份） | 低 | 中 | Marvis 天然擅长，零学习成本 |
| **P1** | 盘中监控截图替代方案 | 中 | 高 | 大幅减少 API 调用 |
| **P1** | Quant 数据脚本定时执行 | 低 | 中 | 一行指令即可 |
| **P1** | 财报/文章 Browser 采集 | 中 | 高 | 解决反爬问题 |
| **P2** | Quant Docker 自动启停 | 低 | 低 | 锦上添花 |
| **P2** | GitHub Actions 监控 | 低 | 低 | 已经有 CI 通知 |

---

## 五、Marvis 侧具体指令清单

### 立即可下达的指令（复制粘贴到 Marvis）

**1. 定时空盘截图**
```
创建一个自动任务：每个工作日 9:25、10:00、11:00、13:00、14:00
打开同花顺，截取"大盘指数"页面，保存到
~/workbuddy_marvis_bridge/shared/market_data/snapshot_{HHMM}.png
```

**2. 每日复盘截图采集**
```
创建一个自动任务：每个工作日 15:00
打开通达信，依次截取：
1. 上证指数日K线图
2. 深证成指日K线图
3. 板块涨幅排名前10
保存到 ~/workbuddy_marvis_bridge/claw/raw_data/daily_charts/
文件名格式：{类型}_{日期}.png
完成后在 ~/workbuddy_marvis_bridge/claw/tasks/ 写入一个 JSON 任务文件：
{
  "task_id": "当天日期-001",
  "project": "claw",
  "type": "data_collection",
  "source": "marvis",
  "title": "每日复盘-行情截图采集完成",
  "params": {"file_count": 3, "output_dir": "claw/raw_data/daily_charts/"}
}
```

**3. 系统定期维护**
```
创建每周一凌晨00:00执行的自动任务：
1. 删除 ~/WorkBuddy/Claw/ 下所有 __pycache__ 目录
2. 删除 ~/WorkBuddy/QuantTradingSystem/ 下所有 .pyc 文件
3. 检查磁盘剩余空间，低于10%时通知我
4. 检查 Claw 和 QuantTradingSystem 两个目录的 git status，有未提交变更时通知我
```

**4. 财报日历采集**
```
创建每个工作日 8:00 和 17:00 执行的自动任务：
打开浏览器访问东方财富财报日历页面，
抓取今日和未来3天预披露财报的公司列表，
保存为 ~/workbuddy_marvis_bridge/claw/raw_data/earnings_calendar_{date}.csv
```

**5. Quant 数据定时采集**
```
创建每个工作日 8:30 执行的自动任务：
在终端执行 cd ~/WorkBuddy/QuantTradingSystem && python3 scripts/fetch_data.py
执行完成后将输出日志保存到 ~/workbuddy_marvis_bridge/quant/raw_data/fetch_log_{date}.txt
如果执行失败，通知我
```

---

## 六、WorkBuddy 侧需要调整的

| 调整项 | 说明 |
|--------|------|
| 盘中监控自动化 | 从"WebSearch 取数"改为"读取 raw_data/market_data/ 截图 + 辅助 API" |
| 每日复盘自动化 | 增加"读取 raw_data/daily_charts/ 截图"步骤 |
| 财报预警 | Marvis 接管采集后，WorkBuddy 只做分析推送 |
| 自动化数量 | 可从 26 个精简到 ~22 个（合并 5 个盘中监控为 1 个） |

---

## 七、预期收益汇总

| 维度 | 改造前 | 改造后 |
|------|--------|--------|
| WorkBuddy API 调用/天 | ~60 次 | ~40 次（-33%） |
| 盘中数据来源 | 纯 API | API + 真实截图交叉验证 |
| 数据采集可靠性 | 受反爬限制 | Browser Agent 继承登录态 |
| 系统维护 | 手动/脚本 | Marvis 自动 |
| 复盘报告 | 纯文本 | 含 K 线截图 |
| Quant 数据采集 | 手动 | 定时自动 |
