#!/usr/bin/env python3
"""
bridge_notify.py — 跨平台通知模块
支持: macOS(osascript)、Linux(notify-send)、飞书 Webhook
用法:
  python3 bridge_notify.py <title> <message> [--platform auto|macos|linux|feishu]
"""

import json
import subprocess
import sys
from pathlib import Path

BRIDGE_DIR = Path.home() / "workbuddy_marvis_bridge"
CONFIG_FILE = BRIDGE_DIR / "shared" / "config" / "config.json"


def load_config() -> dict:
    try:
        with open(CONFIG_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def detect_platform() -> str:
    """自动检测当前平台"""
    if sys.platform == "darwin":
        return "macos"
    elif sys.platform.startswith("linux"):
        return "linux"
    else:
        return "unknown"


def notify_macos(title: str, message: str) -> bool:
    """macOS 系统通知"""
    try:
        subprocess.run(
            [
                "osascript",
                "-e",
                f'display notification "{message}" with title "{title}" sound name "Glass"',
            ],
            capture_output=True,
            timeout=5,
        )
        return True
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def notify_linux(title: str, message: str) -> bool:
    """Linux 桌面通知 (notify-send)"""
    try:
        subprocess.run(
            ["notify-send", title, message, "--icon=dialog-information"],
            capture_output=True,
            timeout=5,
        )
        return True
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def notify_feishu(title: str, message: str) -> bool:
    """飞书 Webhook 通知
    优先级: 环境变量 FEISHU_WEBHOOK > config.json notifications.feishu_webhook
    """
    import os
    webhook_url = os.environ.get("FEISHU_WEBHOOK", "")

    if not webhook_url:
        config = load_config()
        webhook_url = config.get("notifications", {}).get("feishu_webhook", "")

    if not webhook_url:
        print("[bridge_notify] 飞书 webhook 未配置，跳过", file=sys.stderr)
        return False

    try:
        import urllib.request

        payload = json.dumps(
            {
                "msg_type": "interactive",
                "card": {
                    "header": {
                        "title": {"tag": "plain_text", "content": title},
                        "template": "blue",
                    },
                    "elements": [
                        {"tag": "markdown", "content": message},
                        {
                            "tag": "note",
                            "elements": [
                                {
                                    "tag": "plain_text",
                                    "content": f"Bridge Notify · {_now_str()}",
                                }
                            ],
                        },
                    ],
                },
            }
        ).encode("utf-8")

        req = urllib.request.Request(
            webhook_url, data=payload, headers={"Content-Type": "application/json"}
        )
        urllib.request.urlopen(req, timeout=5)
        return True
    except Exception as e:
        print(f"[bridge_notify] 飞书通知失败: {e}", file=sys.stderr)
        return False


def _now_str() -> str:
    from datetime import datetime

    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def send(title: str, message: str, platform: str | None = None) -> dict[str, bool]:
    """发送通知，返回各平台结果"""
    platform = platform or detect_platform()
    results: dict[str, bool] = {}

    # 始终尝试飞书（如果有配置）
    results["feishu"] = notify_feishu(title, message)

    # 桌面通知
    if platform == "macos":
        results["desktop"] = notify_macos(title, message)
    elif platform == "linux":
        results["desktop"] = notify_linux(title, message)

    return results


def main() -> None:
    if len(sys.argv) < 3:
        print("用法: python3 bridge_notify.py <title> <message> [--platform macos|linux|feishu]")
        sys.exit(1)

    title = sys.argv[1]
    message = sys.argv[2]
    platform = None

    for arg in sys.argv[3:]:
        if arg.startswith("--platform="):
            platform = arg.split("=", 1)[1]
        elif arg == "--platform" and len(sys.argv) > sys.argv.index(arg) + 1:
            platform = sys.argv[sys.argv.index(arg) + 1]

    results = send(title, message, platform)

    for name, ok in results.items():
        status = "✅" if ok else "❌"
        print(f"  {status} {name}")

    # 至少一个成功就算 OK
    if any(results.values()):
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
