#!/usr/bin/env python3
"""
feishu_qa.py — 飞书问答轮询引擎 v1
读取飞书群聊消息 → 识别未处理的用户提问 → 输出待处理任务列表

设计原则:
1. 轻量快速（不调用 AI）
2. 读写 processed_ids.json 做幂等
3. 输出格式化为 JSON 供后续 AI 处理
"""

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BRIDGE_DIR = Path.home() / "workbuddy_marvis_bridge"
FEISHU_DIR = BRIDGE_DIR / "feishu-inbound"
PROCESSED_FILE = FEISHU_DIR / "processed_ids.json"
CONFIG_FILE = FEISHU_DIR / "config.json"
CHAT_ID = "oc_9ee5303497f5e0e71666b610d6bdc346"


def load_processed() -> dict:
    if PROCESSED_FILE.exists():
        return json.loads(PROCESSED_FILE.read_text())
    return {"ids": {}}


def save_processed(data: dict):
    PROCESSED_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROCESSED_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def run_lark(args: list) -> dict:
    cmd = ["lark-cli"] + args
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        return {"ok": False, "error": result.stderr}
    return json.loads(result.stdout)


def fetch_recent_messages(minutes: int = 30) -> list:
    """获取最近 minutes 分钟内的群消息"""
    now = datetime.now(timezone(timedelta(hours=8)))
    start = now - timedelta(minutes=minutes)

    result = run_lark([
        "im", "+chat-messages-list",
        "--chat-id", CHAT_ID,
        "--as", "bot",
        "--start", start.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "--format", "json",
        "--page-size", "50"
    ])

    if not result.get("ok"):
        print(f"WARN: Failed to fetch messages: {result.get('error')}", file=sys.stderr)
        return []

    messages = result.get("data", {}).get("messages", [])
    return messages


def is_user_message(msg: dict) -> bool:
    """判断是否为用户发送的消息（非机器人自身）"""
    sender = msg.get("sender", {})
    sender_type = sender.get("sender_type", "")
    return sender_type == "user"


def main():
    processed = load_processed()
    ids = processed.get("ids", {})

    messages = fetch_recent_messages(minutes=60)

    new_messages = []
    for msg in messages:
        msg_id = msg.get("message_id", "")
        if not msg_id or msg_id in ids:
            continue
        if not is_user_message(msg):
            continue

        new_messages.append({
            "message_id": msg_id,
            "content": msg.get("content", ""),
            "message_type": msg.get("msg_type", ""),
            "create_time": msg.get("create_time", ""),
            "sender": msg.get("sender", {}),
        })

    if new_messages:
        # Write results to stdout for the automation to consume
        output = {
            "found": len(new_messages),
            "messages": new_messages
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print(json.dumps({"found": 0, "messages": []}))


if __name__ == "__main__":
    main()
