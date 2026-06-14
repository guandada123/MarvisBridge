#!/usr/bin/env python3
"""四项目统一状态汇总
聚合 MarvisBridge / Claw / StockInsight / QTS 健康状态，输出摘要 + 可选飞书推送。

用法:
    python3 status_aggregator.py             # 终端输出
    python3 status_aggregator.py --json      # JSON 输出
    python3 status_aggregator.py --alert     # 异常时飞书推送
"""

import argparse
import json
import os
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

HOME = Path.home()
MARVIS_DIR = HOME / "workbuddy_marvis_bridge"
CLAW_HEARTBEAT = HOME / "WorkBuddy" / "Claw" / ".workbuddy" / "data" / "heartbeat.json"
STOCKINSIGHT_HEALTH_URL = "http://localhost:8765/api/health"
FEISHU_WEBHOOK = os.environ.get("FEISHU_WEBHOOK", "")


def check_marvis() -> dict:
    """检查 MarvisBridge 健康状态"""
    result = {"name": "MarvisBridge", "status": "unknown", "details": []}

    # 检查 core 脚本
    core_scripts = [
        "scripts/bridge_monitor.sh",
        "scripts/bridge_notify.py",
        "scripts/health_check.sh",
    ]
    for s in core_scripts:
        if (MARVIS_DIR / s).exists():
            result["details"].append(f"✅ {s}")
        else:
            result["details"].append(f"❌ {s} 缺失")
            result["status"] = "critical"

    # 检查心跳文件
    heartbeat = MARVIS_DIR / "status" / "heartbeat"
    if heartbeat.exists():
        try:
            with open(heartbeat) as f:
                ts = f.read().strip()
            age = time.time() - float(ts)
            if age < 300:
                result["details"].append(f"✅ 心跳正常 ({int(age)}s前)")
            else:
                result["details"].append(f"🟡 心跳过旧 ({int(age)}s前)")
                result["status"] = "warning"
        except (ValueError, OSError):
            result["details"].append("❌ 心跳文件异常")
            result["status"] = "critical"
    else:
        result["details"].append("❌ 心跳文件缺失")
        result["status"] = "critical"

    if result["status"] == "unknown":
        result["status"] = "healthy"

    return result


def check_claw() -> dict:
    """检查 Claw 心跳"""
    result = {"name": "Claw", "status": "unknown", "details": []}

    if not CLAW_HEARTBEAT.exists():
        result["status"] = "warning"
        result["details"].append("🟡 心跳文件未生成")
        return result

    try:
        with open(CLAW_HEARTBEAT) as f:
            data = json.load(f)
        last_hb = data.get("last_heartbeat", "")
        healthy = data.get("healthy", False)
        deps = data.get("dependencies", {})

        if last_hb:
            try:
                hb_time = datetime.fromisoformat(last_hb)
                age_h = (datetime.now() - hb_time).total_seconds() / 3600
                result["details"].append(f"{'✅' if age_h < 2 else '🟡'} 最后心跳: {age_h:.1f}h前")
            except Exception:
                result["details"].append("⚠️ 无法解析心跳时间")

        for dep, ok in deps.items():
            result["details"].append(f"{'✅' if ok else '❌'} {dep}")

        if healthy:
            result["status"] = "healthy"
        else:
            result["status"] = "critical"
    except Exception:
        result["status"] = "critical"
        result["details"].append("❌ 心跳文件解析失败")

    return result


def check_stockinsight() -> dict:
    """检查 StockInsight API 健康"""
    result = {"name": "StockInsight", "status": "unknown", "details": []}

    try:
        req = urllib.request.Request(STOCKINSIGHT_HEALTH_URL)
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            status = data.get("status", "")
            uptime = data.get("uptime_seconds", 0)
            result["details"].append(f"{'✅' if status == 'ok' else '❌'} status={status}")
            if uptime:
                result["details"].append(f"   uptime: {uptime:.0f}s")
            result["status"] = "healthy" if status == "ok" else "critical"
    except urllib.error.URLError:
        result["status"] = "warning"
        result["details"].append("🟡 API 不可达（可能未启动）")
    except Exception as e:
        result["status"] = "critical"
        result["details"].append(f"❌ 检查异常: {e}")

    return result


def check_qts() -> dict:
    """检查 QTS 服务健康（仅 Docker 环境有效）"""
    result = {"name": "QTS", "status": "unknown", "details": []}

    # 检查 docker-compose.yml 是否存在
    compose = HOME / "WorkBuddy" / "QuantTradingSystem" / "docker-compose.yml"
    if not compose.exists():
        result["status"] = "warning"
        result["details"].append("🟡 docker-compose.yml 缺失")
        return result

    # 检查关键服务端口
    services = {
        "strategy-service": "http://localhost:8000/health",
        "execution-service": "http://localhost:8001/health",
        "ai-scheduler": "http://localhost:8002/health",
    }

    any_running = False
    for name, url in services.items():
        try:
            req = urllib.request.Request(url)
            urllib.request.urlopen(req, timeout=3)
            result["details"].append(f"✅ {name}")
            any_running = True
        except Exception:
            result["details"].append(f"🟡 {name} 未运行")

    if any_running:
        result["status"] = "healthy"
    else:
        result["status"] = "warning"
        result["details"].append("   Docker 环境可能未启动")

    return result


def send_summary(results: list[dict]) -> bool:
    """聚合结果推送到飞书"""
    if not FEISHU_WEBHOOK:
        print("⚠️ FEISHU_WEBHOOK 未配置，跳过推送", file=sys.stderr)
        return False

    status_map = {"healthy": "🟢", "warning": "🟡", "critical": "🔴", "unknown": "⚪"}
    lines = []
    critical_count = 0

    for r in results:
        icon = status_map.get(r["status"], "⚪")
        if r["status"] == "critical":
            critical_count += 1
        lines.append(f"{icon} **{r['name']}**: {r['status']}")

    template = "red" if critical_count > 0 else "blue"

    payload = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": "🔍 四项目状态汇总"},
                "template": template,
            },
            "elements": [
                {
                    "tag": "markdown",
                    "content": f"**检查时间**: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n" + "\n".join(lines),
                },
                {"tag": "note", "elements": [{"tag": "plain_text", "content": "status_aggregator.py · 每6小时自动巡检"}]},
            ],
        },
    }

    try:
        req = urllib.request.Request(
            FEISHU_WEBHOOK,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            if result.get("code") == 0:
                print("✅ 状态汇总已推送飞书")
                return True
            else:
                print(f"❌ 飞书返回错误: {result}", file=sys.stderr)
                return False
    except Exception as e:
        print(f"❌ 飞书推送失败: {e}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(description="四项目统一状态汇总")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    parser.add_argument("--alert", action="store_true", help="异常时飞书推送")
    args = parser.parse_args()

    results = [check_marvis(), check_claw(), check_stockinsight(), check_qts()]

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print(f"🔍 四项目状态 | {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        status_map = {"healthy": "🟢", "warning": "🟡", "critical": "🔴", "unknown": "⚪"}
        for r in results:
            icon = status_map.get(r["status"], "⚪")
            print(f"\n{icon} {r['name']}: {r['status']}")
            for d in r["details"]:
                print(f"  {d}")

    if args.alert:
        send_summary(results)

    # 退出码：有 critical 则非0
    critical = sum(1 for r in results if r["status"] == "critical")
    sys.exit(1 if critical > 0 else 0)


if __name__ == "__main__":
    main()
