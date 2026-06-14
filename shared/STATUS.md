# 项目状态看板（全系统）

> 更新: 2026-06-11 14:10 | 供马维斯每日读取

---

## 一、项目总览

| 项目 | 代号 | 阶段 | 进度 | 阻塞 | 桥接状态 | 优先级 |
|------|------|------|:--:|:--:|:------:|:------:|
| A股投资辅助系统 | **claw** | 生产运行 | 85% | P0×1 P1×1 | ✅ 已挂接 | 🔴 最高 |
| A股量化交易系统 | **quant** | 预生产验证 | 65% | P3×1 | ✅ 已挂接 | 🟡 高 |
| 桥接调度系统 | **bridge** | v3.1 直连 | 78% | P0×1 P1×1 | - | 🔴 最高 |
| 项目进度驾驶舱 | **dashboard** | 🆕 已上线 | 100% | 0 | ✅ 已挂接 | 🟢 中 |
| 微信公众号RSS | **wemprss** | 功能受阻 | 45% | P1×1 | 🔴 未挂接 | 🟡 高 |
| 全链路量化参考 | **stock_insight** | 分析借鉴 | 10% | 0 | ✅ 已挂接 | 🟢 参考 |
| 自动化任务群 | **automations** | 31/31 ACTIVE | 90% | P2×1 | 🔴 未挂接 | 🟡 高 |
| 数据源体系 | **datasource** | 5主源+多备源 | 70% | P3×1 | 🔴 未挂接 | 🟢 中 |

> 💡 **看 dashboard 实时状态**: 打开 `project-dashboard.html` — 含进度条/甘特图/P0-P3阻塞筛选

---

## 二、claw — 投资辅助系统

### 模拟持仓
```
总资产: ¥28,608 | 现金: ¥596 | 月收益: -4.64%
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
紫光国微 002049  200股 | 成本 ¥76.86 | 现价 ¥73.00 (-5.00%)
士兰微   600460  400股 | 成本 ¥35.08 | 现价 ¥33.53 (-4.43%)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚠️ 行业集中度：100% 半导体 | 现金枯竭无法开仓
```

### 阻塞项
| 严重度 | 问题 | 需要谁 |
|:------:|------|--------|
| 🔴 | 现金仅 ¥596，无法开新仓 | 等士兰微回本卖出 |
| 🟡 | 微信读书 Cookie 过期 | 用户扫码续期 |
| 🟡 | 微信公众号 Cookie 过期 | 用户操作续期 |
| 🟡 | GitHub Token 未配置 | Marvis 提供 |

### 今日任务：7/7 已完成

---
## 十二、dashboard — 项目进度驾驶舱 🆕

| 属性 | 值 |
|------|-----|
| 文件 | `/Users/guan/WorkBuddy/2026-06-11-06-53-32/project-dashboard.html` |
| 定位 | 4项目+10阻塞项实时可视化 |
| 桥接路径 | `bridge/dashboard/` |
| 状态 | 🟢 已上线 |

### 阻塞全景（本节由北辰维护，马维斯据此生成任务）

| 严重度 | 项目 | 阻塞项 | → 马维斯可执行任务 |
|:------:|------|------|------|
| 🔴 P0 | Claw | 现金仅¥596，无法开新仓 | ⚠️ 模拟盘自主决策，非阻塞 |
| 🔴 P0 | Bridge | file_watcher需手动重启 | ✅ 已自愈(PID 96966, heartbeat正常, fswatch检测任务) |
| 🟠 P1 | Claw | GitHub Token未提供 | ⏳ 需用户提供Token |
| 🟠 P1 | QTS | 35个文件未提交Git | ✅ 已推送(4 commits on origin/main, workflow已排除) |
| 🟠 P1 | Bridge | qclaw-dev路由失败 | ✅ QClaw已退役, bridge v3.3 direct模式 |
| 🟠 P1 | we-mp-rss | CSS选择器失败 | ⚠️ 确诊为Session过期(非CSS), 需用户扫码 http://localhost:18001 |
| 🟡 P2 | QTS | .env可能未配置完整 | ✅ 核心值已配置(Tushare/DeepSeek/飞书/DB), 可选字段留空正常 |
| 🟡 P2 | Bridge | 死信待清理 | ✅ 仅1封(20260610-041), 为格式校验失败, 已确认安全 |
| 🟡 P2 | we-mp-rss | 5个公众号采集中断 | ✅ 登录后自动恢复 |
| 🟡 P2 | Automations | 静默失败风险 | ✅ poller运行中, 3任务已迁移并消费, workbuddy_pending/已恢复 |
| 🔵 P3 | QTS | TA-Lib arm64编译 | ✅ Docker内编译绕过 |
| 🔵 P3 | Claw | watcher重启需手动 | ✅ 同 Bridge P0，合并处理 |
| 🔵 P3 | Datasource | Python 3.13 C扩展冲突 | ✅ 暂用系统3.9 |

---
## 十三、wemprss — 微信公众号RSS 🆕

### 当前现状
- Docker服务运行（端口18001），密钥已配置，Skill已安装，6个公众号已订阅
- **阻塞**: 微信公众号平台 Session 过期 → 抓取器返回 "Invalid Session"
- **根因** (2026-06-11 确诊): 非 CSS 选择器问题，是 WeChat 登录态失效导致页面为二维码/登录页而非文章列表

### 阻塞项
| 严重度 | 问题 | 需要谁 |
|:------:|------|--------|
| 🟠 P1 | WeChat Session 过期 | 用户访问 http://localhost:18001 扫码登录 |
| 🟡 P2 | 5个公众号采集中断 | 登录后自动恢复采集 |

---
## 十四、马维斯行动建议（v3 — 含 P0→Task 映射） — 全链路量化参考项目（新增 🆕）

| 属性 | 值 |
|------|-----|
| 仓库 | https://github.com/nguyenchunghieu799-blip/stock-insight |
| 本地路径 | /Users/guan/WorkBuddy/stock-insight/ (5.5MB) |
| 定位 | A股全链路量化分析平台，为 Claw/QTS 提供参考 |
| 状态 | ✅ 代码审查已完成，报告见 output/stock-insight-review.md |

### 核心模块（73个Python文件）
| 模块 | 可借鉴点 |
|------|------|
| `quant.py` | 7因子量化评分（动量/技术/基本面/量能/风险/舆情/资金流） |
| `enhanced_screener.py` | 大盘→板块→个股三过滤 + 双轮筛选 |
| `patterns.py` | 27种K线形态识别（含中文解读） |
| `nl_report.py` | 规则引擎多空辩论 + 自然语言报告 |
| `report_html.py` | Chart.js交互式HTML报告 |
| `self_audit.py` | 6大系统健康检查项 |
| `cli.py` | 15子命令统一CLI + 延迟导入优化 |
| `cache.py` | 三级缓存：内存→SQLite→API |

### 马维斯可执行任务
- 代码审查 — 提取 `quant.py` 多因子模型到 QTS strategy-service
- 代码审查 — 提取 `enhanced_screener.py` 板块过滤逻辑到 Claw 选股
- 报告生成 — 借鉴 HTML 交互报告方案优化 Claw 日报
- 模式提取 — 多源数据容灾 + 三级缓存架构 → QTS 数据层优化
- 方案设计 — K线形态识别集成到现有技术分析链路

### 待办
- [x] 克隆仓库到本地 `/Users/guan/WorkBuddy/stock-insight/`
- [x] Marvis 审查 `quant.py` / `enhanced_screener.py` 提取核心算法 → 报告: output/stock-insight-review.md
- [ ] 移植 `composite_quant_score` + 追高惩罚到 QTS strategy-service
- [ ] 移植 K线形态识别到 Claw 日报

---

## 四、quant — 量化交易系统

### 系统状态
| 组件 | 状态 |
|------|:----:|
| strategy-service (8000) | 🟢 200 OK |
| execution-service (8001) | 🟢 200 OK |
| ai-scheduler (8002) | 🟢 200 OK |
| PostgreSQL | 🟢 quant_trading 已就绪 |
| Docker (14容器) | 🟢 全部启动验证通过 |
| git | 🟢 已推送(5 commits on origin/main, workflow已排除) |
| K8s Secret | 🟡 9 密钥未注入 |

---

## 五、automations — 自动化任务群（31/31 ACTIVE）

### 4.1 投资类（22个）

| 分类 | 数量 | 模型 | 典型触发 |
|------|:--:|------|------|
| 盘中监控/问答 | 4 | deepseek-reasoner | 工作日 9-14 |
| 盘前/收盘/早报 | 4 | deepseek-reasoner | 工作日 7:30-15:05 |
| 周期总结(周/月/季/年) | 3 | deepseek-v4-pro | 周六/周日/月1 |
| 美股监控 | 3 | deepseek-reasoner | 周二-六 21:00-04:30 |
| 投顾操盘(选股/复盘/周期) | 7 | deepseek-v4-pro | 工作日 |
| 其他投资 | 2 | deepseek-v4-flash | 每日 20:00 / 周六 |

### 4.2 系统维护类（7个）

| 分类 | 数量 | 模型 | 典型触发 |
|------|:--:|------|------|
| 工作空间清理/报告 | 3 | deepseek-reasoner | 周末 |
| 记忆维护(健康/索引/梳理) | 4 | deepseek-reasoner | 周日/月1 |

### 4.3 知识库+桥接（2个）

| 名称 | 调度 |
|------|------|
| 知识库文章归档索引 | 每日 22:00 |
| Marvis Bridge Monitor v3 | 工作日 9-15 每小时 |

### 4.4 健康风险
| 风险 | 影响 |
|------|------|
| 模型 400 错误 | ⚠️ 2026-06-10 已修复（model ID 迁移至 custom-local: 前缀） |
| 飞书推送去重 | 🟢 正常 |
| 自动化静默失败 | 🟢 poller运行正常, 队列已清空, 今日3轮任务完成 |

### 桥接状态
| 指标 | 值 |
|------|-----|
| 挂接状态 | ✅ 已挂接 |
| 监控方式 | Marvis 每日读 STATUS.md 中的 automations 章节 |
| 健康感知 | 通过 STATUS.md 的自动化任务数量变化感知异常 |

---

## 六、datasource — 数据源体系

| 数据源 | 类型 | 状态 | 用途 |
|------|------|:--:|------|
| tdx-connector MCP | 主 | 🟢 | A股行情/K线/板块 |
| 腾讯财经 API | 备 | 🟢 | 实时行情(3-5s延迟) |
| 东方财富 API | 备 | 🟢 | 资金流向/北向/情绪 |
| AKShare (系统Python 3.9) | 新增 | 🟢 | 宏观因子/资产指数/FF因子 |
| AKShare (托管Python 3.13) | 新增 | 🔴 | C扩展签名冲突，全部C包不可用 |
| 微信读书 | 采集 | 🟡 | Cookie过期 |
| 微信公众号 | 采集 | 🟡 | Cookie过期 |

---

## 七、bridge — 桥接系统

| 指标 | 值 |
|------|-----|
| 模式 | v3.1 直连（无中间层） |
| 今日循环 | 3轮 / 7+3任务已完成 |
| pending | 空（全部归档） |
| 信号目录 | `status/signals/` — 马维斯已可轮询 |
| watcher | 🟡 PID 已停止（06:51），heartbeat 陈旧 23h+ |
| workbuddy_pending | 🟢 已恢复，目录重建完成 |
| claw/tasks 写入偏差 | ⚠️ 马维斯任务持续写入 claw/tasks/ 而非 workbuddy_pending/（补偿: scripts/task_sync.sh） |

---

## 八、skills — 技能/Skills（37个）

| 分类 | 数量 | 关键技能 |
|------|:--:|------|
| 投资金融 | 15 | stock-realtime-quote, backtest-strategy, mx-finance-search 等 |
| 工具 | 10 | agent-browser, excel-xlsx, pdf-analyzer 等 |
| 平台 | 5 | marvis-bridge, memory-extractor, ontology 等 |
| 安全 | 4 | moltguard, security-auditor, skill-scanner 等 |
| 维护 | 3 | auto-updater, self-improving-agent 等 |

---

## 九、connectors — 连接器

| 连接器 | 状态 | 用途 |
|------|:--:|------|
| feishu | 🟢 | 飞书推送/IM/文档/日历 |
| github | 🟢 | 代码仓库 |
| tdx-connector | 🟢 | 通达信行情 |
| ima-mcp | 🟢 | ima知识库 |

其余 20+ 连接器未连接（按需启用）。

---

## 十、近期完成（今日两循环）

| 循环 | 任务 | 结果 |
|:--:|------|------|
| 1 | 001-004 | 研报索引 / 数据基础设施(部分) / 持仓监控 / Docker验证 |
| 2 | 005-007 | AKShare修复 / DB确认 / 信号约定 |
| 3 | 008-010 | Docker启动(14容器) / strategy category修复 / 任务迁移 |

---

## 十四、马维斯行动建议（v3 — 含 P0→Task 映射）

### P0 阻塞自动转化规则 🆕
马维斯每日读取本文件后，**自动为 P0 阻塞项生成任务**：
```
P0 阻塞项 → 写入 status/workbuddy_pending/{YYYYMMDD}-P0-{SEQ}.json
格式: { "task_id", "project", "priority": "critical", "type": "fix",
         "title": "解决 P0 阻塞: {标题}", "blocker_ref": "STATUS.md#十二" }
```

### 每日行动
1. **读本文件** → 扫描 P0 阻塞 → 自动生成任务到 `workbuddy_pending/`
2. **检查 `status/signals/`** → 响应实时信号
3. **打开 `dashboard/results/dashboard_status.md`** → 获取完整4项目+10阻塞全景 🆕

### 本周重点
1. **🔴 P0 优先**: watcher 自动重拉（Bridge P0）— ✅ 已解决
2. **🟠 P1 其次**: GitHub Token 提供 / ~~QTS git commit~~ ✅ / we-mp-rss 选择器修复
3. **🟡 P2**: ~~死信清理~~ ✅ / ~~自动化产出审计~~ ✅
4. **🆕 StockInsight**: 代码审查任务 → 提取优秀模式到 Claw/QTS
5. **🆕 Dashboard**: 每日读 `dashboard_status.md`，感知全局项目健康
