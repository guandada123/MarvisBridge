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
  python3 bridge_monitor_tools.py log-aggregate <minutes> [log_dir]
  python3 bridge_monitor_tools.py clean-dedup [dedup_dir] [ttl_seconds]

设计目标: 消除 bridge_monitor.sh 中每次 python3 -c 内联调用带来的进程启动开销。
"""

import json
import os
import sys
import time
from pathlib import Path

# Python 3.11+ has datetime.UTC; 3.9 compat fallback
try:
    from datetime import UTC
except ImportError:
    UTC = UTC

# 安全白名单：防止 project 字段路径穿越
VALID_PROJECTS = {"claw", "quant", "dashboard", "stock_insight", "shared"}


def sanitize_project(project: str) -> str:
    """强制 project 字段只能是白名单值，防止路径穿越"""
    if not project or project not in VALID_PROJECTS:
        return "claw"
    return project


# 任务文件最大尺寸限制（1MB）
MAX_TASK_FILE_SIZE = 1 * 1024 * 1024


def safe_load_json(path: Path) -> dict:
    """安全加载 JSON，带文件大小限制"""
    stat = path.stat()
    if stat.st_size > MAX_TASK_FILE_SIZE:
        raise ValueError(f"Task file too large: {stat.st_size} bytes (max {MAX_TASK_FILE_SIZE})")
    with open(path) as f:
        return json.load(f)


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
        data = safe_load_json(task_file)
        value = data.get(field, default)
        print(value if value is not None else default)
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
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
        data = safe_load_json(task_file)
    except (OSError, json.JSONDecodeError, ValueError) as e:
        print(f"ERROR: cannot read task: {e}", file=sys.stderr)
        sys.exit(1)

    # 添加入队时间戳
    data["bridge_enqueued_at"] = int(time.time())

    with open(dest, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # 输出任务元信息供 shell 使用
    project = sanitize_project(data.get("project", ""))
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
        data = safe_load_json(task_file)
    except (OSError, json.JSONDecodeError, ValueError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    project = sanitize_project(data.get("project", ""))
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
            data = safe_load_json(pending_file)
        except (OSError, json.JSONDecodeError, ValueError):
            continue

        enqueued_at = data.get("bridge_enqueued_at", 0)
        if enqueued_at == 0:
            # 由 cp/mv 直接移入的文件（如 task_sync.sh），无 enqueued_at → 视为刚到达，跳过过期检查
            continue
        age = now - enqueued_at

        if age <= ttl_sec:
            continue

        # 过期，写入死信
        project = sanitize_project(data.get("project", ""))
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
            ["pgrep", "-f", "fswatch.*workbuddy_pending"], capture_output=True, text=True, timeout=5
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

            # 兼容 Python 3.9: +0800 → +08:00 标准化
            normalized = last_raw
            if len(last_raw) == 25 and last_raw[-5] in ("+", "-"):
                # 格式: 2026-06-16T07:56:56+0800 → 2026-06-16T07:56:56+08:00
                normalized = last_raw[:-2] + ":" + last_raw[-2:]
            last_dt = datetime.fromisoformat(normalized)
            if last_dt.tzinfo is not None:
                last_dt = last_dt.astimezone(UTC)
            age = int((datetime.now(UTC) - last_dt).total_seconds())
        except (ValueError, AttributeError):
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


def cmd_acquire_lock(args: list[str]) -> None:
    """获取互斥锁，成功返回 0，失败返回非 0
    增强：O_CREAT|O_EXCL 原子抢锁 + PID 僵尸检测
    Usage: acquire-lock <lock_name> <timeout_sec>
    """
    if len(args) < 2:
        print("Usage: acquire-lock <lock_name> <timeout_sec>", file=sys.stderr)
        sys.exit(1)

    lock_name = args[0]
    timeout_sec = int(args[1])
    lock_dir = BRIDGE_DIR / "status" / "locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_file = lock_dir / f"{lock_name}.lock"
    pid_file = lock_dir / f"{lock_name}.pid"

    now = int(time.time())
    my_pid = os.getpid()

    def _try_acquire() -> bool:
        """O_EXCL 原子抢锁，返回 True=成功 False=失败"""
        try:
            fd = os.open(str(lock_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(now).encode())
            os.close(fd)
            pid_file.write_text(str(my_pid))
            return True
        except FileExistsError:
            return False

    def _is_lock_stale() -> bool:
        """检查锁是否过期或持有进程已死"""
        old_pid = None
        if pid_file.exists():
            try:
                old_pid = int(pid_file.read_text().strip())
            except (ValueError, OSError):
                pass
        if old_pid is not None:
            try:
                os.kill(old_pid, 0)
                return False  # PID 存活 → 锁有效
            except OSError:
                return True  # PID 不存在 → 僵尸锁
        # 旧格式兼容：仅靠时间判断
        try:
            lock_ts = int(lock_file.read_text().strip())
            return now - lock_ts >= timeout_sec  # 超时则视为 stale
        except (ValueError, OSError):
            return True

    # 第 1 次：尝试原子抢锁
    if _try_acquire():
        sys.exit(0)

    # 锁存在 → 检查是否僵尸锁
    if _is_lock_stale():
        # 删除旧锁后重试（最多一次）
        try:
            lock_file.unlink(missing_ok=True)
            pid_file.unlink(missing_ok=True)
        except OSError:
            pass
        if _try_acquire():
            sys.exit(0)

    # 锁被真实持有
    sys.exit(1)


def cmd_update_field(args: list[str]) -> None:
    """更新任务 JSON 文件中的单个字段
    Usage: update-field <task_json> <field> <value>
    """
    if len(args) < 3:
        print("Usage: update-field <task_json> <field> <value>", file=sys.stderr)
        sys.exit(1)

    task_file = Path(args[0])
    field = args[1]
    value = args[2]

    try:
        data = safe_load_json(task_file)
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        sys.exit(1)

    # 尝试类型转换（使用 try/except 替代 isdigit，避免 Unicode digit 漏洞）
    if value.lower() in ("true", "false"):
        value = value.lower() == "true"
    elif value.lower() == "null":
        value = None
    else:
        try:
            value = int(value)
        except ValueError:
            try:
                value = float(value)
            except ValueError:
                pass  # 保持字符串原值

    data[field] = value

    with open(task_file, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"OK|{field}={value}")


def cmd_log_aggregate(args: list[str]) -> None:
    """聚合日志 ERROR 统计，输出最近 N 分钟的异常摘要
    Usage: log-aggregate <minutes> <log_dir>
    输出: JSON 格式，含各组件 ERROR 计数和最新异常
    """
    from collections import Counter
    from datetime import datetime, timedelta

    minutes = int(args[0]) if args else 10
    log_dir = Path(args[1]) if len(args) > 1 else BRIDGE_DIR / "logs"

    # 统一使用本地时区（日志记录的时区），避免 UTC/本地 naive 混用
    cutoff = datetime.now() - timedelta(minutes=minutes)
    errors: Counter[str] = Counter()
    latest_errors: list[str] = []
    total_lines = 0

    for log_file in sorted(log_dir.glob("*.log")):
        try:
            with open(log_file) as f:
                for line in f:
                    total_lines += 1
                    ts_str = line[1:20] if line.startswith("[") else ""
                    if ts_str:
                        try:
                            ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                        except ValueError:
                            ts = cutoff - timedelta(days=1)  # force skip
                    else:
                        continue
                    if ts < cutoff:
                        continue
                    if "ERROR" in line or "CRITICAL" in line:
                        # 提取组件名
                        comp = "unknown"
                        parts = line.split("][")
                        for p in parts:
                            p = p.strip("[]")
                            if p not in ("", "ERROR", "CRITICAL", "WARN", "INFO"):
                                comp = p
                                break
                        errors[comp] += 1
                        if len(latest_errors) < 5:
                            latest_errors.append(line.rstrip()[:200])
        except OSError:
            continue

    output = {
        "period_minutes": minutes,
        "total_log_lines": total_lines,
        "error_summary": dict(errors.most_common()),
        "total_errors": sum(errors.values()),
        "latest_errors": latest_errors,
        "generated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
    }
    print(json.dumps(output, ensure_ascii=False))


def cmd_clean_dedup(args: list[str]) -> None:
    """清理 watcher 去重缓存中过期的条目
    Usage: clean-dedup <dedup_dir> [ttl_seconds]
    """
    dedup_dir = Path(args[0]) if args else BRIDGE_DIR / "status" / ".dedup_cache"

    if not dedup_dir.exists():
        print("OK|0|no cache dir")
        return

    now = int(time.time())
    cleaned = 0
    for cache_file in dedup_dir.iterdir():
        if not cache_file.is_file():
            continue
        try:
            expire_ts = int(cache_file.read_text().strip())
            if now > expire_ts:
                cache_file.unlink()
                cleaned += 1
        except (OSError, ValueError):
            cache_file.unlink()
            cleaned += 1

    print(f"OK|{cleaned}|cleaned expired dedup entries")


def cmd_update_dashboard(args: list[str]) -> None:
    """更新 dashboard.json 状态快照"""
    _ = args  # unused

    status_dir = BRIDGE_DIR / "status"
    status_dir.mkdir(parents=True, exist_ok=True)

    # 收集数据
    pending_dir = status_dir / "workbuddy_pending"
    pending_count = len(list(pending_dir.glob("*.json"))) if pending_dir.exists() else 0

    dead_total = 0
    for proj in ("claw", "quant"):
        dl_dir = BRIDGE_DIR / proj / "dead_letter"
        if dl_dir.exists():
            dead_total += len(list(dl_dir.glob("*.json")))

    # watcher 状态
    watcher_pid_file = status_dir / "watcher.pid"
    watcher_alive = False
    watcher_pid = None
    if watcher_pid_file.exists():
        try:
            pid = int(watcher_pid_file.read_text().strip())
            os.kill(pid, 0)
            watcher_alive = True
            watcher_pid = pid
        except (OSError, ValueError):
            pass

    from datetime import datetime, timedelta, timezone

    tz = timezone(timedelta(hours=8))
    now = datetime.now(tz)

    dashboard = {
        "dashboard_version": "1.0.0",
        "updated_at": now.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "last_scan": now.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "watcher": {
            "alive": watcher_alive,
            "pid": watcher_pid,
        },
        "tasks_today": {
            "pending": pending_count,
            "dead_lettered": dead_total,
        },
        "projects": {
            "claw": {
                "dead_letters": len(list((BRIDGE_DIR / "claw" / "dead_letter").glob("*.json")))
                if (BRIDGE_DIR / "claw" / "dead_letter").exists()
                else 0
            },
            "quant": {
                "dead_letters": len(list((BRIDGE_DIR / "quant" / "dead_letter").glob("*.json")))
                if (BRIDGE_DIR / "quant" / "dead_letter").exists()
                else 0
            },
        },
        "circuit_breakers": {"open": [], "half_open": [], "closed": []},
    }

    dashboard_file = status_dir / "dashboard.json"
    with open(dashboard_file, "w") as f:
        json.dump(dashboard, f, ensure_ascii=False, indent=2)
    print(f"OK|{dashboard_file}")


def cmd_get_fields(args: list[str]) -> None:
    """读取任务 JSON 文件中的多个字段，空格分隔输出"""
    if len(args) < 2:
        print("Usage: get-fields <task_json> <field1> [field2] ...", file=sys.stderr)
        sys.exit(1)

    task_file = Path(args[0])
    fields = args[1:]

    try:
        data = safe_load_json(task_file)
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
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
        "acquire-lock": cmd_acquire_lock,
        "update-field": cmd_update_field,
        "update-dashboard": cmd_update_dashboard,
        "gen-health-json": cmd_gen_health_json,
        "log": cmd_log,
        "log-aggregate": cmd_log_aggregate,
        "clean-dedup": cmd_clean_dedup,
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
