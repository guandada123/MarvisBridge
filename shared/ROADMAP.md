# 项目路线图（全系统 Marvis 驱动版）

> 最后更新: 2026-06-11 | 版本: v2.0
> 用途: 马维斯据此制定任务、分配优先级、追踪进度

---

## 一、项目概览

| 项目 | 代号 | 阶段 | 桥接 | 优先级 |
|------|------|------|:--:|:------:|
| A股投资辅助系统 | **claw** | 生产运行 + 持续优化 | ✅ | 🔴 最高 |
| A股量化交易系统 | **quant** | 开发完成 → 预生产验证 | ✅ | 🟡 高 |
| 桥接调度系统 | **bridge** | v3.1 稳定 | — | 🟢 中 |
| 自动化任务群 | **automations** | 31/31 ACTIVE | 🔜 待挂接 | 🟡 高 |
| 数据源体系 | **datasource** | 5主源+备源 | 🔜 待挂接 | 🟢 中 |

---

## 二、claw — A股投资辅助系统

### 当前现状
- 22 个自动化定时任务运行中
- 通达信 MCP 主数据源，腾讯财经/东方财富/AKShare 备选
- 模拟持仓 2 只，现金仅 ¥596
- 微信读书/公众号 Cookie 过期

### 里程碑

#### M1: 解决阻塞项（本周）
- [ ] 微信读书 Cookie 续期（需用户扫码）
- [ ] 微信公众号 Cookie 续期（需用户操作）
- [ ] GitHub Token 配置

#### M2: 持仓调仓（本周）
- [ ] 士兰微回本卖出（触发价 ¥35.08）
- [ ] 资金释放后配置杰瑞股份(002353) / 沪电股份(002463)
- [ ] 目标：现金恢复至可操作水平

#### M3: 策略数据基础设施（2周内）
- [ ] macro_data.py 创建（AKShare 已就绪，系统Python 3.9）
- [ ] market_data.py 大类资产指数扩展
- [ ] FF3/FF5 因子数据接入
- [ ] 股债相关性监控上线（代码已写入 cron_monitor.py，缺债券数据源）

#### M4: 策略升级（1个月内）
- [ ] Tesseract OCR 安装
- [ ] 研报 PDF → 向量索引 → 语义搜索
- [ ] 因子轮动策略扩展
- [ ] "研报→因子→策略→回测→交易" 全链路

#### M5: 系统加固（持续）
- [ ] 数据源双活机制
- [ ] 自动化健康检查日报
- [ ] 飞书推送去重 + 合并优化

---

## 三、quant — A股量化交易系统

### 里程碑

#### M1: 本地验证（本周） ✅
- [x] docker-compose up 14 容器启动
- [x] PostgreSQL 建库验证
- [x] 8000/8001/8002 端口响应
- [ ] git 手动提交（Sandbox 阻止）

#### M2: 部署与联调（2周内）
- [ ] K8s Secret 注入（9 个 API 密钥）
- [ ] MiniQMT 接口联调
- [ ] 全链路端到端测试

#### M3: 生产加固（1个月内）
- [ ] 依赖安全漏洞修复
- [ ] PostgreSQL 主从复制
- [ ] Redis 高可用

#### M4: 投产（1-2个月）
- [ ] 实盘账户对接
- [ ] 生产环境部署
- [ ] 飞书告警全链路

---

## 四、automations — 自动化任务群（31个）

### 当前现状
- 31 个全部 ACTIVE，模型已迁移至自建 DeepSeek API
- 无暂停/故障项
- ⚠️ 不在桥接管理下（Marvis 无法感知自动化健康状态）

### 里程碑

#### M1: 挂接到桥接（本周）
- [ ] 在 STATUS.md 中添加自动化健康摘要
- [ ] 每日自动化产出检查脚本
- [ ] 静默失败告警（自动化运行但产出为空）

#### M2: 马维斯可见（2周内）
- [ ] 自动化运行结果 → 写入 bridge 共享目录
- [ ] 马维斯可读取自动化最近产出时间
- [ ] 异常自动升级为 task

---

## 五、datasource — 数据源体系

### 里程碑

#### M1: AKShare 完全就绪（本周）
- [ ] 系统 Python 3.9 AKShare 验证通过 ✅
- [ ] 托管 Python 3.13 C扩展签名冲突解决
- [ ] 所有 macro_data.py 数据接口测试通过

#### M2: 双活机制（2周内）
- [ ] 主备数据源自动切换
- [ ] 数据质量校验
- [ ] 降级通知

---

## 六、bridge — 桥接调度系统

### 当前现状
- v3.1 简化直连模式
- 马维斯 → workbuddy_pending/ → WorkBuddy 轮询
- 信号文件 `status/signals/` 已建立

### 里程碑
- [x] 协作开发规则 v2.1（含自动执行规则） ✅
- [x] 信号文件约定 ✅
- [ ] 全项目覆盖（automations + datasource）
- [ ] Bridge 健康检查脚本

---

## 七、马维斯任务驱动节奏

| 频率 | 动作 | 产出 |
|------|------|------|
| **每日** | 读 STATUS.md → 检查 signals/ → 写 workbuddy_pending/*.json | 1-5 个新任务 |
| **每日** | 轮询 signals/done_*.json → 感知完成 | 状态同步 |
| **每周** | 对比 ROADMAP vs 实际进度 → 调整优先级 | ROADMAP 更新 |
| **每月** | 自动化健康审计 → 产出统计 → 异常排查 | 审计报告 |
| **阻塞时** | 升级请求 → 即时决策 | 技术方案 |

### 任务写入格式
```json
{
  "task_id": "YYYYMMDD-NNN",
  "project": "claw | quant | bridge | automations | datasource",
  "priority": "high | medium | low",
  "type": "code | deploy | maintenance | audit | fix | feature",
  "title": "任务简述",
  "description": "详细说明",
  "action_items": ["步骤1", "步骤2"],
  "reference": { "handbook": "路径" }
}
```
写入路径: `~/workbuddy_marvis_bridge/status/workbuddy_pending/{task_id}.json`
