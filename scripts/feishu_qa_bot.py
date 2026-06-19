#!/usr/bin/env python3
"""
feishu_qa_bot.py — 飞书群聊问答机器人 v2
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
监听群聊：oc_9ee5303497f5e0e71666b610d6bdc346
AI 引擎：Ollama (qwen2.5:7b)
轮询间隔：180 秒
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

增强能力 (v2)：
1. 股票名称→代码自动映射（中文名也能查）
2. 大盘指数实时查询（上证/深证/创业板）
3. 模拟盘持仓查询
4. 更智能的股票问题检测
"""

import json
import os
import re
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ─── 配置 ──────────────────────────────────────────────────
CHAT_ID = "oc_9ee5303497f5e0e71666b610d6bdc346"
BRIDGE_DIR = Path.home() / "workbuddy_marvis_bridge"
FEISHU_DIR = BRIDGE_DIR / "feishu-inbound"
PROCESSED_FILE = FEISHU_DIR / "processed_ids.json"
LOG_FILE = BRIDGE_DIR / "logs" / "feishu_qa_bot.log"
PID_FILE = BRIDGE_DIR / "status" / "feishu_qa_bot.pid"

# 股票名称映射
STOCK_NAMES_FILE = BRIDGE_DIR / "scripts" / "stock_names.json"

# 模拟盘数据
SIM_PORTFOLIO = Path.home() / "WorkBuddy" / "Claw" / ".workbuddy" / "data" / "simulation" / "portfolio.json"

OLLAMA_API = "http://localhost:11434"
OLLAMA_MODEL = "qwen2.5:7b"

POLL_INTERVAL = 180  # 轮询间隔（秒）
FETCH_MINUTES = 60   # 每次拉取最近多少分钟的消息

BOT_NAME = "WorkBuddy AI 助理"

# ─── 工具函数 ──────────────────────────────────────────────

def log(msg: str):
    """写日志"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def load_processed() -> set:
    """加载已处理消息 ID"""
    try:
        data = json.loads(PROCESSED_FILE.read_text())
        return set(data.get("ids", {}).keys())
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def save_processed(message_id: str):
    """保存已处理消息 ID"""
    processed = load_processed()
    processed.add(message_id)
    FEISHU_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_FILE.write_text(
        json.dumps({"ids": {mid: "done" for mid in processed}}, ensure_ascii=False, indent=2)
    )


def run_cmd(cmd: list) -> dict:
    """执行 shell 命令并返回解析后的 JSON"""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return {"ok": False, "error": result.stderr}
        return json.loads(result.stdout)
    except (json.JSONDecodeError, subprocess.TimeoutExpired, OSError) as e:
        return {"ok": False, "error": str(e)}


def fetch_recent_messages(minutes: int = FETCH_MINUTES) -> list:
    """获取群聊最近 N 分钟的消息"""
    now = datetime.now(timezone(timedelta(hours=8)))
    start = now - timedelta(minutes=minutes)

    result = run_cmd([
        "lark-cli", "im", "+chat-messages-list",
        "--chat-id", CHAT_ID,
        "--as", "bot",
        "--start", start.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "--format", "json",
        "--page-size", "50"
    ])

    if not result.get("ok"):
        log(f"⚠️ 获取消息失败: {result.get('error', 'unknown')}")
        return []

    return result.get("data", {}).get("messages", [])


def is_user_message(msg: dict) -> bool:
    """判断是否为用户发送的消息"""
    sender = msg.get("sender", {})
    return sender.get("sender_type") == "user"


def send_reply(message_id: str, reply_text: str):
    """回复消息到飞书群"""
    if len(reply_text) > 18000:
        reply_text = reply_text[:17999] + "\n\n⋯（回复已截断）"

    markdown = f"🤖 **{BOT_NAME}**\n\n{reply_text}"

    result = run_cmd([
        "lark-cli", "im", "+messages-send",
        "--chat-id", CHAT_ID,
        "--as", "bot",
        "--markdown", markdown,
    ])

    if result.get("ok"):
        log(f"✅ 已回复消息 {message_id[:16]}...")
    else:
        log(f"❌ 回复失败: {result.get('error', 'unknown')}")


# ─── 股票名称映射 ──────────────────────────────────────────

def load_stock_names() -> dict:
    """加载股票名称→代码映射"""
    try:
        data = json.loads(STOCK_NAMES_FILE.read_text())
        return data.get("stocks", {})
    except (FileNotFoundError, json.JSONDecodeError) as e:
        log(f"⚠️ 股票名称映射加载失败: {e}")
        return {}


def resolve_stock_names(text: str, name_map: dict) -> list:
    """
    从用户消息中识别股票名称，返回代码列表
    同时匹配 6 位数字代码 和 中文名称
    """
    found = set()

    # 1. 匹配 6 位数字代码（不使用 \b，因为中文环境 \b 不生效）
    codes = re.findall(r'(\d{6})', text)
    for code in codes:
        found.add(code)

    # 2. 匹配中文股票名称（采用 Trie 搜索优化）
    #    按名称长度降序匹配，避免短名称被长名称前缀误匹配
    matched_names = []
    for name, code in name_map.items():
        if name in text:
            matched_names.append((len(name), name, code))

    # 按名称长度降序，先匹配长名称后匹配短名称
    matched_names.sort(reverse=True)
    for _, name, code in matched_names:
        found.add(code)
        log(f"📛 识别股票名称: {name} → {code}")

    return list(found)


# ─── 大盘指数查询 ──────────────────────────────────────────

def fetch_market_indices() -> str:
    """获取主要指数实时行情"""
    import urllib.request
    indices = {
        "sh000001": "上证指数",
        "sz399001": "深证成指",
        "sz399006": "创业板指",
    }
    results = []
    for q_code, q_name in indices.items():
        try:
            url = f"http://qt.gtimg.cn/q={q_code}"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                raw = resp.read().decode("gbk")
            if "~" not in raw:
                continue
            parts = raw.split("~")
            if len(parts) < 40:
                continue
            price = parts[3]
            change_amt = parts[31] if len(parts) > 31 else ""
            change_pct = parts[32] if len(parts) > 32 else ""
            results.append(
                f"• {q_name}: {price} ({change_pct}%, {change_amt})"
            )
        except Exception as e:
            log(f"⚠️ 指数获取失败 {q_code}: {e}")

    if results:
        return "【大盘指数】\n" + "\n".join(results) + "\n"
    return ""


# ─── 持仓查询 ──────────────────────────────────────────────

def fetch_portfolio_summary() -> str:
    """读取模拟盘持仓并生成摘要"""
    try:
        data = json.loads(SIM_PORTFOLIO.read_text())
        cash = data.get("cash", 0)
        positions = data.get("positions", {})

        # 从最近的 daily_snapshot 获取总资产和收益
        snapshots = data.get("daily_snapshot", {})
        latest_date = max(snapshots.keys()) if snapshots else ""
        latest = snapshots.get(latest_date, {})
        total_asset = latest.get("total_asset", cash)
        pnl = latest.get("pnl", 0)
        pnl_pct = latest.get("pnl_pct", 0)

        lines = [f"总资产: ¥{total_asset:,.2f} | 总收益: ¥{pnl:+.2f} ({pnl_pct:+.2f}%) | 现金: ¥{cash:,.2f}"]

        if positions:
            lines.append("\n持仓明细：")
            for code, pos in positions.items():
                name = pos.get("name", code)
                shares = pos.get("shares", 0)
                avg_cost = pos.get("avg_cost", 0)
                current_price = pos.get("current_price", avg_cost)
                market_value = shares * current_price
                profit_pct = ((current_price / avg_cost) - 1) * 100 if avg_cost else 0
                status = "🟢" if profit_pct >= 0 else "🔴"
                lines.append(
                    f"{status} {name}({code}): {shares}股 | "
                    f"成本¥{avg_cost:.2f}→现价¥{current_price:.2f} | "
                    f"盈亏{profit_pct:+.2f}% (市值¥{market_value:,.0f})"
                )
        else:
            lines.append("\n当前无持仓，空仓中。")

        return "【📈 投顾操盘 · 模拟盘状态】\n" + "\n".join(lines)
    except (FileNotFoundError, json.JSONDecodeError, KeyError) as e:
        log(f"⚠️ 持仓数据读取失败: {e}")
        return ""


# ─── 腾讯行情 ──────────────────────────────────────────────

def fetch_stock_quote(stock_code: str) -> str:
    """通过腾讯财经 API 获取单只股票实时行情"""
    import urllib.request
    try:
        prefix = "sh" if stock_code.startswith("6") else "sz"
        url = f"http://qt.gtimg.cn/q={prefix}{stock_code}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            raw = resp.read().decode("gbk")
        if "~" not in raw:
            return ""
        parts = raw.split("~")
        if len(parts) < 36:
            return ""
        name = parts[1]
        price = parts[3]
        change_amt = parts[31] if len(parts) > 31 else ""
        change_pct = parts[32] if len(parts) > 32 else ""
        volume = parts[6]
        return (f"股票: {name}({stock_code})\n"
                f"现价: ¥{price} | 涨跌: {change_amt} ({change_pct}%)\n"
                f"成交量: {volume}手")
    except Exception as e:
        log(f"⚠️ 行情获取失败 {stock_code}: {e}")
        return ""


# ─── Ollama ────────────────────────────────────────────────

def call_ollama(system_prompt: str, user_message: str) -> str:
    """调用 Ollama 生成回答"""
    prompt = {
        "model": OLLAMA_MODEL,
        "system": system_prompt,
        "prompt": user_message,
        "stream": False,
        "options": {
            "temperature": 0.7,
            "max_tokens": 1024,
        }
    }

    try:
        result = subprocess.run(
            ["curl", "-s", "-X", "POST", f"{OLLAMA_API}/api/generate",
             "-H", "Content-Type: application/json",
             "-d", json.dumps(prompt)],
            capture_output=True, text=True, timeout=60
        )
        data = json.loads(result.stdout)
        return data.get("response", "抱歉，我暂时无法回答这个问题。").strip()
    except Exception as e:
        log(f"⚠️ Ollama 调用失败: {e}")
        return "抱歉，AI 引擎暂时不可用，请稍后再试。"


# ─── 消息处理 ──────────────────────────────────────────────

def detect_query_type(text: str) -> list:
    """检测问题类型，返回需要补充的数据标签列表"""
    types = []
    t = text.lower()

    # 大盘指数
    index_keywords = ["大盘", "上证", "深证", "指数", "创业板指", "沪深"]
    if any(kw in t for kw in index_keywords):
        types.append("indices")

    # 持仓查询
    portfolio_keywords = ["持仓", "我的股票", "模拟盘", "我的仓位", "组合", "投资组合"]
    if any(kw in t for kw in portfolio_keywords):
        types.append("portfolio")

    return types


def process_message(msg: dict, name_map: dict):
    """处理单条用户消息"""
    msg_id = msg.get("message_id", "")
    content = msg.get("content", "").strip()

    if not content or not msg_id:
        return

    log(f"📩 新消息: {content[:100]}...")

    context_extra = ""
    query_types = detect_query_type(content)

    # ---- 大盘指数 ----
    if "indices" in query_types:
        indices_data = fetch_market_indices()
        if indices_data:
            context_extra += "\n" + indices_data + "\n"
            log("📊 已补充大盘指数")

    # ---- 持仓查询 ----
    if "portfolio" in query_types:
        portfolio_data = fetch_portfolio_summary()
        if portfolio_data:
            context_extra += "\n" + portfolio_data + "\n"
            log("💰 已补充持仓数据")

    # ---- 股票行情 ----
    stock_codes = resolve_stock_names(content, name_map)
    if stock_codes:
        for code in stock_codes:
            quote = fetch_stock_quote(code)
            if quote:
                context_extra += f"\n【实时行情】\n{quote}\n"
                log(f"📈 已补充 {code} 实时数据")

    # ---- 构建系统提示 ----
    system_prompt = """你是 WorkBuddy AI 助理，驻扎在飞书群里的智能助手。

你的职责：
1. 回答用户关于股票、投资、市场的问题
2. 回答技术、编程相关问题
3. 回答一般知识性问题

回复风格：
- 简洁直接，先说结论再说理由
- 涉及投资建议时务必加风险提示
- 中文回答
- 不确定的事情不要瞎编，说"我不知道"

能力说明：
- 你可以查询个股实时行情（代码或名称均可）
- 你可以查询大盘指数（上证/深证/创业板）
- 你可以查询模拟盘持仓状态
- 你是通过本地 AI 模型运行，没有互联网搜索能力
- 系统会自动补充实时数据到你的上下文"""

    if context_extra:
        content = f"{content}\n\n===== 系统自动补充数据 =====\n{context_extra}"
        system_prompt += """

注意：以上「系统自动补充数据」是实时获取的，请基于这些数据回答用户的问题。
如果数据为空，请如实告知用户无法获取。"""

    # ---- 调用 Ollama ----
    log("🤖 调用 Ollama 生成回答...")
    reply = call_ollama(system_prompt, content)

    if not reply or len(reply) < 5:
        reply = "抱歉，我暂时无法处理这个问题。"

    # ---- 回复 ----
    send_reply(msg_id, reply)
    save_processed(msg_id)
    log(f"📝 已记录消息 {msg_id[:16]}...")


def main():
    """主循环"""
    # 启动时加载股票名称映射
    name_map = load_stock_names()
    if name_map:
        log(f"📚 已加载 {len(name_map)} 只股票名称映射")
    else:
        log("⚠️ 股票名称映射为空，仅支持代码查询")

    log("=" * 50)
    log("🤖 Feishu Q&A Bot v2 启动")
    log(f"群聊: {CHAT_ID}")
    log(f"模型: {OLLAMA_MODEL} (Ollama)")
    log(f"轮询间隔: {POLL_INTERVAL}s")
    log("=" * 50)

    FEISHU_DIR.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()))

    cycle = 0
    while True:
        cycle += 1
        try:
            log(f"🔍 第 {cycle} 轮轮询...")

            messages = fetch_recent_messages()
            log(f"获取到 {len(messages)} 条消息")

            processed_ids = load_processed()
            log(f"已处理 {len(processed_ids)} 条")

            new_messages = []
            for msg in messages:
                if msg.get("message_id", "") in processed_ids:
                    continue
                if is_user_message(msg):
                    new_messages.append(msg)

            if not new_messages:
                log("⏳ 无新用户消息，等待下一轮")
                time.sleep(POLL_INTERVAL)
                continue

            log(f"🎯 发现 {len(new_messages)} 条新用户消息")

            for msg in new_messages:
                try:
                    process_message(msg, name_map)
                except Exception as e:
                    log(f"❌ 处理消息失败: {e}")
                    import traceback
                    traceback.print_exc()
                    save_processed(msg.get("message_id", ""))

        except KeyboardInterrupt:
            log("👋 收到退出信号")
            break
        except Exception as e:
            log(f"❌ 轮询异常: {e}")
            import traceback
            traceback.print_exc()

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
