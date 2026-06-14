#!/usr/bin/env python3
"""
bridge_monitor_tools.py — 为 bridge_monitor.sh 提供批量 JSON 操作
使用方法:
  python3 bridge_monitor_tools.py get-config <key_path> [default]
  python3 bridge_monitor_tools.py get-task-field <task_json> <field> [default]
  python3 bridge_monitor_tools.py get-fields <task_json> <field1> [field2] ...
  python3 bridge_monitor_tools.py enqueue-pending <task_json> <pending_dir>
  python3 bridge_monitor_tools.py write-dead-letter <task_json> <reason> <dl_base_dir>
  python3 bridge_monitor_tools.py check-expired <pending_dir> <ttl_sec> <dl_base_dir>

设计目标: 消除 bridge_monitor.sh 中每次 python3 -c 内联调用带来的进程启动开销。
"""

import json
import os
import sys
import time
from datetime import UTC
from pathlib import Path

BRIDGE_DIR = Path.home() / "workbuddy_marvis_bridge"
CONFIG_FILE = BRIDGE_DIR / "shared" / "config" / "config.json"


def load_config() -> dict:
    """安全加载 bridge 配置"""
    try:
        with open(CONFIG_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def cmd_get_config(args: list[str]) -> None:
    """读取 config.json 中的嵌套键值"""
    if len(args) < 1:
        print("Usage: get-config <key_path> [default]", file=sys.stderr)
        sys.exit(1)

    key_path = args[0]
    default = args[1] if len(args) > 1 else ""
    config = load_config()

    # 支持点号分隔的嵌套路径，如 automation.scan_interval_seconds
    value = config
    for key in key_path.split("."):
        if isinstance(value, dict):
            value = value.get(key)
        else:
            value = None
            break
        if value is None:
            break

    print(value if value is not None else default)


def cmd_get_task_field(args: list[str]) -> None:
    """读取任务 JSON 文件中的字段"""
    if len(args) < 2:
        print("Usage: get-task-field <task_json> <field> [default]", file=sys.stderr)
        sys.exit(1)

    task_file = Path(args[0])
    field = args[1]
    default = args[2] if len(args) > 2 else ""

    try:
        with open(task_file) as f:
            data = json.load(f)
        value = data.get(field, default)
        print(value if value is not None else default)
    except (FileNotFoundError, json.JSONDecodeError):
        print(default)


def cmd_enqueue_pending(args: list[str]) -> None:
    """将任务文件复制到 pending 目录并写入 enqueued_at 时间戳"""
    if len(args) < 2:
        print("Usage: enqueue-pending <task_json> <pending_dir>", file=sys.stderr)
        sys.exit(1)

    task_file = Path(args[0])
    pending_dir = Path(args[1])

    if not task_file.exists():
        print(f"ERROR: task file not found: {task_file}", file=sys.stderr)
        sys.exit(1)

    pending_dir.mkdir(parents=True, exist_ok=True)

    task_id = task_file.stem
    dest = pending_dir / f"{task_id}.json"

    try:
        with open(task_file) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"ERROR: cannot read task: {e}", file=sys.stderr)
        sys.exit(1)

    # 添加入队时间戳
    data["bridge_enqueued_at"] = int(time.time())

    with open(dest, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # 输出任务元信息供 shell 使用
    project = data.get("project", "claw")
    target = data.get("target_agent", "")
    print(f"ENQUEUED|{task_id}|{project}|{target}")


def cmd_write_dead_letter(args: list[str]) -> None:
    """将失败任务写入死信队列"""
    if len(args) < 3:
        print("Usage: write-dead-letter <task_json> <reason> <dl_base_dir>", file=sys.stderr)
        sys.exit(1)

    task_file = Path(args[0])
    reason = args[1]
    dl_base_dir = Path(args[2])

    try:
        with open(task_file) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    project = data.get("project", "claw")
    dl_dir = dl_base_dir / project / "dead_letter"
    dl_dir.mkdir(parents=True, exist_ok=True)

    task_id = task_file.stem
    dl_file = dl_dir / f"{task_id}_{int(time.time())}.json"

    data["dead_letter_reason"] = reason
    data["dead_letter_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    data["status"] = "dead_lettered"

    with open(dl_file, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"OK|{dl_file}")


def cmd_check_expired(args: list[str]) -> None:
    """扫描 pending 目录，回收过期任务到死信队列"""
    if len(args) < 3:
        print("Usage: check-expired <pending_dir> <ttl_sec> <dl_base_dir>", file=sys.stderr)
        sys.exit(1)

    pending_dir = Path(args[0])
    ttl_sec = int(args[1])
    dl_base_dir = Path(args[2])

    if not pending_dir.exists():
        sys.exit(0)

    now = int(time.time())
    expired_count = 0

    for pending_file in sorted(pending_dir.glob("*.json")):
        try:
            with open(pending_file) as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue

        enqueued_at = data.get("bridge_enqueued_at", 0)
        age = now - enqueued_at

        if age <= ttl_sec:
            continue

        # 过期，写入死信
        project = data.get("project", "claw")
        dl_dir = dl_base_dir / project / "dead_letter"
        dl_dir.mkdir(parents=True, exist_ok=True)

        task_id = pending_file.stem
        dl_file = dl_dir / f"{task_id}_expired_{now}.json"

        data["dead_letter_reason"] = f"WorkBuddy 未在 {ttl_sec}s 内消费，已过期回收"
        data["dead_letter_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        data["status"] = "dead_lettered"

        with open(dl_file, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        pending_file.unlink()
        print(f"EXPIRED|{pending_file}|{age}s|{dl_file}")
        expired_count += 1

    if expired_count == 0:
        print("OK|0")


def cmd_log(args: list[str]) -> None:
    """输出标准化日志行: [ISO8601][组件][级别] 消息"""
    if len(args) < 2:
        print("Usage: log <component> <level> <message>", file=sys.stderr)
        sys.exit(1)
    component = args[0]
    level = args[1]
    message = " ".join(args[2:]) if len(args) > 2 else ""
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}][{component}][{level}] {message}")


def cmd_gen_health_json(args: list[str]) -> None:
    """生成健康检查 JSON 输出，替代 Shell 手动拼接"""
    import subprocess

    bridge_dir = Path(args[0]) if args else BRIDGE_DIR
    status_dir = bridge_dir / "status"

    checks: dict[str, dict[str, str]] = {}
    issues: list[str] = []
    all_healthy = True

    # watcher
    watcher_pid_file = status_dir / "watcher.pid"
    if watcher_pid_file.exists():
        try:
            pid = int(watcher_pid_file.read_text().strip())
            os.kill(pid, 0)
            checks["watcher"] = {"status": "healthy", "detail": f"PID={pid}"}
        except (OSError, ValueError):
            checks["watcher"] = {"status": "dead", "detail": "PID文件存在但进程不存在"}
            all_healthy = False
            issues.append(f"watcher 进程已死亡 (PID={pid})")
    else:
        checks["watcher"] = {"status": "missing", "detail": "无PID文件"}
        all_healthy = False
        issues.append("watcher 未启动")

    # monitor
    monitor_pid_file = status_dir / "monitor.pid"
    if monitor_pid_file.exists():
        try:
            pid = int(monitor_pid_file.read_text().strip())
            os.kill(pid, 0)
            checks["monitor"] = {"status": "healthy", "detail": f"PID={pid}"}
        except (OSError, ValueError):
            checks["monitor"] = {"status": "dead", "detail": "PID文件存在但进程不存在"}
            all_healthy = False
            issues.append(f"monitor 进程已死亡 (PID={pid})")
    else:
        checks["monitor"] = {"status": "missing", "detail": "无PID文件"}
        all_healthy = False
        issues.append("monitor 未启动")

    # fswatch
    try:
        result = subprocess.run(
            ["pgrep", "-f", "fswatch.*claw/tasks"], capture_output=True, text=True, timeout=5
        )
        fswatch_count = len(result.stdout.strip().split("\n")) if result.stdout.strip() else 0
    except Exception:
        fswatch_count = 0

    if fswatch_count > 0:
        checks["fswatch"] = {"status": "healthy", "detail": f"{fswatch_count}个进程"}
    else:
        checks["fswatch"] = {"status": "dead", "detail": "无fswatch进程"}
        all_healthy = False
        issues.append("fswatch 未运行")

    # heartbeat
    heartbeat_file = status_dir / "heartbeat"
    if heartbeat_file.exists():
        last_raw = heartbeat_file.read_text().strip()
        try:
            from datetime import datetime

            # Try ISO format
            last_dt = datetime.fromisoformat(last_raw)
            age = int((datetime.now(UTC) - last_dt.replace(tzinfo=UTC)).total_seconds())
        except ValueError:
            age = 999
        if age < 180:
            checks["heartbeat"] = {"status": "healthy", "detail": f"{age}s前"}
        else:
            checks["heartbeat"] = {"status": "stale", "detail": f"{age}s未更新"}
            all_healthy = False
            issues.append(f"心跳停滞 {age}s")
    else:
        checks["heartbeat"] = {"status": "missing", "detail": "无心跳文件"}
        all_healthy = False
        issues.append("无心跳文件")

    # trigger_queue
    trigger_dir = status_dir / "trigger_queue"
    trigger_count = len(list(trigger_dir.glob("*.json"))) if trigger_dir.exists() else 0
    if trigger_count > 20:
        checks["trigger_queue"] = {"status": "backlogged", "detail": f"{trigger_count}条积压"}
        issues.append(f"trigger_queue 积压 {trigger_count}条")
    else:
        checks["trigger_queue"] = {"status": "healthy", "detail": f"{trigger_count}条"}

    # dead_letter
    dead_total = 0
    for proj in ("claw", "quant"):
        dl_dir = bridge_dir / proj / "dead_letter"
        if dl_dir.exists():
            dead_total += len(list(dl_dir.glob("*.json")))
    if dead_total > 50:
        checks["dead_letter"] = {"status": "warning", "detail": f"{dead_total}封死信"}
        issues.append(f"死信队列累积 {dead_total}封")
    else:
        checks["dead_letter"] = {"status": "healthy", "detail": f"{dead_total}封"}

    # workbuddy_pending
    pending_dir = status_dir / "workbuddy_pending"
    pending_count = len(list(pending_dir.glob("*.json"))) if pending_dir.exists() else 0
    if pending_count > 10:
        checks["workbuddy_pending"] = {"status": "backlogged", "detail": f"{pending_count}条待处理"}
        issues.append(f"WorkBuddy 待处理队列积压 {pending_count}条")
    else:
        checks["workbuddy_pending"] = {"status": "healthy", "detail": f"{pending_count}条"}

    from datetime import datetime

    output = {
        "timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "healthy": all_healthy,
        "checks": checks,
        "issues": issues,
    }
    print(json.dumps(output, ensure_ascii=False))


def cmd_get_fields(args: list[str]) -> None:
    """读取任务 JSON 文件中的多个字段，空格分隔输出"""
    if len(args) < 2:
        print("Usage: get-fields <task_json> <field1> [field2] ...", file=sys.stderr)
        sys.exit(1)

    task_file = Path(args[0])
    fields = args[1:]

    try:
        with open(task_file) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        # 每个字段输出空值
        print(" ".join([""] * len(fields)))
        sys.exit(1)

    values = [str(data.get(f, "")) if data.get(f) is not None else "" for f in fields]
    print(" ".join(values))


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]
    args = sys.argv[2:]

    commands = {
        "get-config": cmd_get_config,
        "get-task-field": cmd_get_task_field,
        "get-fields": cmd_get_fields,
        "gen-health-json": cmd_gen_health_json,
        "log": cmd_log,
        "enqueue-pending": cmd_enqueue_pending,
        "write-dead-letter": cmd_write_dead_letter,
        "check-expired": cmd_check_expired,
    }

    if cmd in commands:
        commands[cmd](args)
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
