#!/usr/bin/env python3
"""
从 Marvis 桥接任务 JSON 中提取 OCR 文本，保存为 .txt 文件。
用法：
  python3 extract_ocr_text.py              # 处理所有未转换的任务
  python3 extract_ocr_text.py --watch      # 持续监听新任务（配合 cron 或 launchd）
  python3 extract_ocr_text.py --file X.json # 处理单个任务文件
"""

import json
import sys
from pathlib import Path

BRIDGE_DIR = Path.home() / "workbuddy_marvis_bridge"
TASKS_DIR = BRIDGE_DIR / "claw" / "tasks"
MARKET_DATA_DIR = BRIDGE_DIR / "shared" / "market_data"


def extract_ocr_from_task(task_file: Path) -> bool:
    """从任务JSON提取ocr_text，保存为对应的.txt文件"""
    try:
        with open(task_file, encoding="utf-8") as f:
            task = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"  [SKIP] {task_file.name}: {e}")
        return False

    # 提取 ocr_text
    ocr_text = task.get("params", {}).get("ocr_text", "")
    if not ocr_text:
        return False

    # 确定输出文件名
    # 从 params.screenshot 推断: "shared/market_data/snapshot_1400.png" -> "snapshot_1400.txt"
    screenshot_path = task.get("params", {}).get("screenshot", "")
    if screenshot_path:
        png_name = Path(screenshot_path).stem  # e.g., "snapshot_1400"
        txt_filename = f"{png_name}.txt"
    else:
        # 从 task_id 推断: "2026-06-10-1400" -> "snapshot_1400.txt"
        task_id = task.get("task_id", "")
        time_part = task_id.split("-")[-1] if "-" in task_id else "unknown"
        txt_filename = f"snapshot_{time_part}.txt"

    txt_path = MARKET_DATA_DIR / txt_filename

    # 如果 .txt 已存在且内容相同，跳过
    if txt_path.exists():
        existing = txt_path.read_text(encoding="utf-8")
        if existing.strip() == ocr_text.strip():
            return False  # 已存在，无需更新

    # 写入
    MARKET_DATA_DIR.mkdir(parents=True, exist_ok=True)
    txt_path.write_text(ocr_text, encoding="utf-8")
    print(f"  [OK] {txt_filename} ({len(ocr_text)} chars)")
    return True


def process_all():
    """处理所有任务JSON"""
    if not TASKS_DIR.exists():
        print(f"任务目录不存在: {TASKS_DIR}")
        return

    task_files = sorted(TASKS_DIR.glob("*.json"))
    converted = 0
    for tf in task_files:
        if extract_ocr_from_task(tf):
            converted += 1

    print(f"\n完成: {converted}/{len(task_files)} 个任务已提取OCR文本")


def process_single(filepath: str):
    """处理单个任务文件"""
    p = Path(filepath)
    if not p.exists():
        print(f"文件不存在: {filepath}")
        sys.exit(1)
    extract_ocr_from_task(p)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        if sys.argv[1] == "--file" and len(sys.argv) > 2:
            process_single(sys.argv[2])
        elif sys.argv[1] == "--watch":
            # 简单轮询模式（可配合 cron 每分钟调用）
            process_all()
        else:
            print(__doc__)
    else:
        process_all()
