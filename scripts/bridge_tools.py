#!/usr/bin/env python3
"""
桥接工具集 v3
- priority_sort: 按优先级排序任务
- acquire_lock: 获取应用操作锁（防并发冲突）
- check_sla: SLA 时延检查
- rotate_data: 30 天数据滚动清理
"""

import glob
import json
import os
import sys
from datetime import datetime, timedelta
from typing import Any

BRIDGE_DIR = os.path.expanduser("~/workbuddy_marvis_bridge")
CONFIG_FILE = os.path.join(BRIDGE_DIR, "shared/config/config.json")
LOCK_DIR = os.path.join(BRIDGE_DIR, "status/locks")


def load_config() -> dict:
    """安全加载 bridge 配置文件，失败返回空字典"""
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, FileNotFoundError, json.JSONDecodeError):
        return {}


# ==================== 1. Priority Sorting ====================
def sort_tasks_by_priority(tasks_dir: str) -> list[tuple[int, str, dict[str, Any]]]:
    """按优先级排序 pending 任务：high > medium > low"""
    priority_order = {"high": 0, "medium": 1, "low": 2}
    tasks = []

    for f in glob.glob(os.path.join(tasks_dir, "*.json")):
        if os.path.basename(f) == "template.json":
            continue
        try:
            with open(f) as fp:
                t = json.load(fp)
            if t.get("status") == "pending":
                p = priority_order.get(t.get("priority", "medium"), 2)
                tasks.append((p, f, t))
        except (OSError, json.JSONDecodeError):
            continue

    tasks.sort(key=lambda x: x[0])
    return tasks


# ==================== 2. Concurrency Lock ====================
def acquire_lock(app_name: str, timeout_seconds: int = 300) -> bool:
    """获取应用操作锁，返回 True=获锁成功"""
    os.makedirs(LOCK_DIR, exist_ok=True)
    lock_file = os.path.join(LOCK_DIR, f"{app_name}.lock")

    # 检查已有锁是否超时
    if os.path.exists(lock_file):
        try:
            with open(lock_file) as f:
                lock_data = json.load(f)
            locked_at = datetime.fromisoformat(lock_data["locked_at"])
            if datetime.now() - locked_at < timedelta(seconds=timeout_seconds):
                return False  # 锁有效，拒绝
        except (json.JSONDecodeError, ValueError, KeyError):
            pass  # 锁损坏，覆盖

    # 创建锁
    with open(lock_file, "w") as f:
        json.dump(
            {
                "app": app_name,
                "locked_at": datetime.now().isoformat(),
                "pid": os.getpid(),
            },
            f,
        )
    return True


def release_lock(app_name: str) -> None:
    """释放锁"""
    lock_file = os.path.join(LOCK_DIR, f"{app_name}.lock")
    if os.path.exists(lock_file):
        os.remove(lock_file)


# ==================== 3. SLA Latency Check ====================
def check_sla(project: str, task_type: str, deadline_minutes: int = 5) -> dict[str, Any]:
    """检查 SLA：任务是否按时完成"""
    result = {
        "violations": [],
        "checked": 0,
        "healthy": True,
    }

    tasks_dir = os.path.join(BRIDGE_DIR, project, "tasks")

    for f in glob.glob(os.path.join(tasks_dir, "*.json")):
        try:
            with open(f) as fp:
                t = json.load(fp)
            if t.get("type") != task_type:
                continue
            if t.get("status") != "pending":
                continue
            if not t.get("deadline"):
                continue

            result["checked"] += 1
            deadline = datetime.fromisoformat(t["deadline"])
            lag = (datetime.now() - deadline).total_seconds() / 60

            if lag > deadline_minutes:
                result["violations"].append(
                    {
                        "task_id": t["task_id"],
                        "title": t.get("title", ""),
                        "deadline": t["deadline"],
                        "lag_minutes": round(lag, 1),
                    }
                )
                result["healthy"] = False
        except (OSError, json.JSONDecodeError, ValueError):
            continue

    return result


# ==================== 4. Data Rotation ====================
def rotate_raw_data(max_age_days: int = 30, dry_run: bool = False) -> dict[str, Any]:
    """清理超过 max_age_days 天的 raw_data 文件"""
    result = {"deleted": [], "freed_mb": 0.0, "dry_run": dry_run}

    raw_dirs = [
        os.path.join(BRIDGE_DIR, "claw", "raw_data"),
        os.path.join(BRIDGE_DIR, "quant", "raw_data"),
        os.path.join(BRIDGE_DIR, "shared", "market_data"),
    ]

    cutoff = datetime.now() - timedelta(days=max_age_days)

    for raw_dir in raw_dirs:
        if not os.path.isdir(raw_dir):
            continue
        for f in glob.glob(os.path.join(raw_dir, "**", "*"), recursive=True):
            if not os.path.isfile(f):
                continue
            mtime = datetime.fromtimestamp(os.path.getmtime(f))
            if mtime < cutoff:
                size_mb = os.path.getsize(f) / (1024 * 1024)
                result["freed_mb"] += size_mb
                result["deleted"].append(os.path.relpath(f, BRIDGE_DIR))

                if not dry_run:
                    os.remove(f)

    result["freed_mb"] = round(result["freed_mb"], 2)
    return result


# ==================== 5. Trading Day Check ====================
def is_trading_day() -> tuple[bool, str]:
    """检查今天是否为交易日"""
    calendar_file = os.path.join(BRIDGE_DIR, "shared/config/trading_calendar.json")
    try:
        with open(calendar_file) as f:
            cal = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return True, "无交易日历，默认允许"

    today = datetime.now().strftime("%Y-%m-%d")

    # 周末检查
    if datetime.now().weekday() >= 5:
        return False, "周末非交易日"

    # 节假日检查
    for holiday_name, dates in cal.get("holidays_2026", {}).items():
        if today in dates:
            return False, f"节假日: {holiday_name} ({today})"

    return True, f"交易日 ({today})"


# ==================== 6. Data Source Resolution ====================
def resolve_data_source(task: dict[str, Any]) -> dict[str, Any]:
    """解析数据采集任务的数据源，返回 {source_name, tool_type, params, fallback}"""
    config = load_config()
    ds_config = config.get("data_sources", {})
    routing = ds_config.get("routing", {})

    params = task.get("params", {})
    data_type = params.get("data_type", "realtime_quote")

    # 确定数据源
    source_key = routing.get(data_type, "realtime_quote")
    source_info = ds_config.get("available", {}).get(source_key, {})

    if not source_info:
        # 尝试从 params.data_source 读取
        source_info = ds_config.get("available", {}).get(params.get("data_source", ""), {})

    if not source_info:
        return {
            "resolved": False,
            "error": f"未找到数据源: data_type={data_type}, source={params.get('data_source', 'N/A')}",
        }

    # 确定回退
    backup_type = f"backup_{data_type}"
    backup_key = routing.get(backup_type, "")
    backup_info = ds_config.get("available", {}).get(backup_key, {}) if backup_key else None

    return {
        "resolved": True,
        "primary": {
            "name": source_key,
            "type": source_info.get("type"),
            "tool": source_info.get("mcp_name") or source_info.get("skill_name"),
            "capabilities": source_info.get("capabilities", []),
        },
        "fallback": {
            "name": backup_key,
            "type": backup_info.get("type"),
            "tool": backup_info.get("mcp_name") or backup_info.get("skill_name"),
        }
        if backup_info
        else None,
        "params": params,
    }


def generate_data_collection_prompt(task: dict[str, Any]) -> str:
    """根据数据采集任务生成 WorkBuddy 执行提示词"""
    source = resolve_data_source(task)
    if not source["resolved"]:
        return f"# 错误: {source['error']}"

    p = source["primary"]
    params = source["params"]
    task_title = task.get("title", "数据采集")

    lines = [
        f"# {task_title}",
        "",
        "## 数据源",
        f"- 主: {p['tool']} ({p['type']})",
    ]
    if source["fallback"]:
        lines.append(f"- 备: {source['fallback']['tool']} ({source['fallback']['type']})")

    lines += [
        "",
        "## 参数",
        "```json",
        json.dumps(params, ensure_ascii=False, indent=2),
        "```",
        "",
        "## 输出",
        f"结果写入: {task.get('params', {}).get('output', 'claw/results/')}",
        "",
        "## 执行方式",
    ]

    if p["type"] == "mcp":
        lines.append(f"使用 MCP 工具 `{p['tool']}` 获取数据，写入指定输出文件。")
    else:
        lines.append(f"加载 `{p['tool']}` skill，按参数采集数据，写入指定输出文件。")

    lines.append("")
    lines.append("如主数据源不可用，自动切换备用数据源。")

    return "\n".join(lines)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""

    if cmd == "sort":
        for d in ["claw", "quant"]:
            tasks_dir = os.path.join(BRIDGE_DIR, d, "tasks")
            tasks = sort_tasks_by_priority(tasks_dir)
            print(f"\n{d}/tasks: {len(tasks)} pending")
            for _p, _f, t in tasks:
                print(f"  {t.get('priority', '?')}: {t['task_id']} {t.get('title', '')}")

    elif cmd == "lock":
        app = sys.argv[2] if len(sys.argv) > 2 else "default"
        if acquire_lock(app):
            print(f"✅ 锁已获取: {app}")
        else:
            print(f"⛔ 锁冲突: {app} 正在使用中")
            sys.exit(1)

    elif cmd == "unlock":
        app = sys.argv[2] if len(sys.argv) > 2 else "default"
        release_lock(app)
        print(f"✅ 锁已释放: {app}")

    elif cmd == "sla":
        project = sys.argv[2] if len(sys.argv) > 2 else "claw"
        task_type = sys.argv[3] if len(sys.argv) > 3 else "data_collection"
        r = check_sla(project, task_type)
        print(f"SLA 检查: {project}/{task_type}")
        print(f"  健康: {'✅' if r['healthy'] else '⚠️'}")
        for v in r["violations"]:
            print(f"  ⚠️ {v['task_id']}: 超时 {v['lag_minutes']}分钟 → {v['title']}")

    elif cmd == "rotate":
        dry_run = "--dry-run" in sys.argv
        r = rotate_raw_data(dry_run=dry_run)
        print(f"数据清理: {'DRY RUN' if dry_run else 'LIVE'}")
        print(f"  清理文件: {len(r['deleted'])} 个")
        print(f"  释放空间: {r['freed_mb']} MB")

    elif cmd == "trading-day":
        ok, msg = is_trading_day()
        print(f"{'✅' if ok else '⏸️'} {msg}")
        sys.exit(0 if ok else 1)

    elif cmd == "resolve-source":
        task_file = sys.argv[2]
        with open(task_file) as f:
            task = json.load(f)
        source = resolve_data_source(task)
        print(json.dumps(source, ensure_ascii=False, indent=2))

    elif cmd == "gen-prompt":
        task_file = sys.argv[2]
        with open(task_file) as f:
            task = json.load(f)
        print(generate_data_collection_prompt(task))

    else:
        print("用法: python3 bridge_tools.py <command>")
        print("  sort           — 按优先级排序 pending 任务")
        print("  lock <app>     — 获取应用操作锁")
        print("  unlock <app>   — 释放锁")
        print("  sla <proj> <type>  — SLA 时延检查")
        print("  rotate [--dry-run] — 30天数据滚动清理")
        print("  trading-day    — 检查今日是否为交易日")
        # QClaw 已退役
        print("  resolve-source <task.json> — 解析数据采集任务的 API 数据源")
        print("  gen-prompt <task.json>     — 生成数据采集执行提示词")
