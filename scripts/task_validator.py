#!/usr/bin/env python3
"""
Marvis-WorkBuddy Bridge 任务格式校验器 v3
- 业务幂等键 (idempotency_key) 去重
- 死信队列 (dead_letter/) 写入
- 熔断器 (circuit_breaker) 检查
- Agent 能力校验 (可选)
- OpenTelemetry trace_id 支持

用法: python3 task_validator.py <task_file.json>
      python3 task_validator.py --config   # 输出当前配置
      python3 task_validator.py --check-circuit <type>  # 检查熔断状态
"""

import fcntl
import glob
import json
import os
import sys
import time
import uuid
from datetime import datetime, timedelta

BRIDGE_DIR = os.path.expanduser("~/workbuddy_marvis_bridge")
LOCK_TIMEOUT = 5  # 秒，文件锁超时


def _with_cb_lock(cb_file: str, mode: str = "r"):
    """以文件锁安全打开 circuit_breaker.json，返回 (file_handle, data)"""
    fd = os.open(cb_file, os.O_RDWR | os.O_CREAT, 0o644)
    deadline = time.time() + LOCK_TIMEOUT
    while time.time() < deadline:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            time.sleep(0.05)
    else:
        os.close(fd)
        raise TimeoutError(f"无法获取 circuit_breaker.json 锁，超时 {LOCK_TIMEOUT}s")

    try:
        data = json.loads(os.read(fd, 4096).decode() or "{}")
    except (json.JSONDecodeError, ValueError):
        data = {}

    return fd, data


def _write_cb_unlock(fd, data: dict):
    """写入数据并解锁"""
    os.lseek(fd, 0, os.SEEK_SET)
    os.ftruncate(fd, 0)
    os.write(fd, json.dumps(data, indent=2).encode())
    fcntl.flock(fd, fcntl.LOCK_UN)
    os.close(fd)


CONFIG_FILE = os.path.join(BRIDGE_DIR, "shared/config/config.json")


def load_config() -> dict:
    """加载统一配置"""
    try:
        with open(CONFIG_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"⚠️  配置加载失败: {e}，使用硬编码回退", file=sys.stderr)
        return _fallback_config()


def _fallback_config() -> dict:
    """硬编码回退配置"""
    return {
        "projects": {"claw": {}, "quant": {}, "shared": {}},
        "valid_types": [
            "data_collection",
            "code_review",
            "data_analysis",
            "report_generation",
            "deploy",
            "test",
            "maintenance",
            "custom",
            "github_ci_check",
            "github_pr_review",
            "social_post",
            "content_publish",
            "wechat_notify",
            "wechat_push",
            "literature_search",
            "data_collect",
            "research",
            "market_snapshot",
            "github_token_request",
        ],  # v3.1: 同步 config.json
        "valid_sources": ["marvis", "workbuddy", "manual"],
        "valid_priorities": ["high", "medium", "low"],
        "valid_statuses": ["pending", "processing", "completed", "failed", "dead_lettered"],
        "required_fields": ["task_id", "project", "type", "source", "title"],
        "idempotency": {"enabled": True, "check_done_dir": True, "use_business_key": True},
        "dead_letter_queue": {"enabled": True, "retention_days": 30},
        "circuit_breaker": {
            "enabled": True,
            "failure_window_minutes": 30,
            "failure_rate_threshold": 0.5,
            "circuit_open_minutes": 30,
        },
        "retry": {"default_max_retries": 3},
    }


def derive_idempotency_key(task: dict) -> str:
    """
    从业务语义派生幂等键
    格式: {project}:{type}:{date}:{business_id}
    其中 date 从 task_id 的 YYYYMMDD 部分提取
    """
    config = load_config()
    key_config = config.get("idempotency", {})
    if not key_config.get("use_business_key", False):
        return ""

    project = task.get("project", "unknown")
    task_type = task.get("type", "unknown")
    task_id = task.get("task_id", "")

    # 从 task_id 提取日期 YYYYMMDD
    date_part = "unknown"
    if task_id and "-" in task_id:
        date_part = task_id.split("-")[0]

    # 业务标识优先从 params 或 trigger_next 获取
    business_id = task.get("trigger_next", "")
    if not business_id:
        seq = task.get("sequence")
        if seq and seq.get("group"):
            business_id = seq["group"]
        else:
            business_id = task.get("title", "unknown").replace(" ", "_")[:30]

    key = f"{project}:{task_type}:{date_part}:{business_id}"
    return key


def check_business_idempotency(idempotency_key: str, project: str) -> tuple[bool, str]:
    """业务幂等键去重检查"""
    if not idempotency_key:
        return True, "无业务幂等键，跳过检查"

    # 检查 done/ 目录
    done_dir = os.path.join(BRIDGE_DIR, project, "done")
    for done_file in glob.glob(os.path.join(done_dir, "*.json")):
        try:
            with open(done_file) as f:
                t = json.load(f)
            existing_key = t.get("idempotency_key", "")
            if existing_key and existing_key == idempotency_key:
                return False, f"业务幂等键 {idempotency_key} 已归档于 {os.path.basename(done_file)}"
        except (OSError, json.JSONDecodeError):
            continue

    # 检查 tasks/ 目录
    tasks_dir = os.path.join(BRIDGE_DIR, project, "tasks")
    for task_file in glob.glob(os.path.join(tasks_dir, "*.json")):
        if os.path.basename(task_file) == "template.json":
            continue
        try:
            with open(task_file) as f:
                t = json.load(f)
            existing_key = t.get("idempotency_key", "")
            if existing_key and existing_key == idempotency_key:
                return False, f"业务幂等键 {idempotency_key} 已在队列中"
        except (OSError, json.JSONDecodeError):
            continue

    return True, "业务幂等键唯一"


def check_circuit_breaker(task_type: str) -> tuple[bool, str]:
    """熔断器检查（文件锁保护，防止并发读写竞态）"""
    config = load_config()
    cb_config = config.get("circuit_breaker", {})
    if not cb_config.get("enabled", False):
        return True, "熔断器未启用"

    cb_file = os.path.join(BRIDGE_DIR, "status", "circuit_breaker.json")

    # 文件锁安全读取
    try:
        fd, cb_state = _with_cb_lock(cb_file)
    except TimeoutError:
        return True, "熔断器文件锁超时，放行"

    circuit = cb_state.get(task_type, {})
    if circuit.get("state") == "open":
        opened_at = circuit.get("opened_at", "")
        circuit_open_minutes = cb_config.get("circuit_open_minutes", 30)
        try:
            opened_time = datetime.fromisoformat(opened_at)
            if datetime.now() - opened_time < timedelta(minutes=circuit_open_minutes):
                _write_cb_unlock(fd, cb_state)
                return (
                    False,
                    f"熔断器开路: {task_type} 故障率 {circuit.get('failure_rate', '?')}%，熔断至 {opened_time + timedelta(minutes=circuit_open_minutes)}",
                )
        except ValueError:
            pass

        # 熔断时间已过，进入半开状态
        circuit["state"] = "half_open"
        circuit["half_open_probes"] = 0
        cb_state[task_type] = circuit
        _write_cb_unlock(fd, cb_state)
        return True, "熔断器半开，允许试探性请求"

    if circuit.get("state") == "half_open":
        probes = circuit.get("half_open_probes", 0)
        max_probes = cb_config.get("half_open_max_probes", 3)
        if probes >= max_probes:
            _write_cb_unlock(fd, cb_state)
            return True, "半开状态探测次数已达上限，放行"
        circuit["half_open_probes"] = probes + 1
        cb_state[task_type] = circuit
        _write_cb_unlock(fd, cb_state)
        return True, "熔断器半开放行"

    _write_cb_unlock(fd, cb_state)
    return True, "熔断器关闭"


def update_circuit_breaker(task_type: str, success: bool):
    """更新熔断器状态（文件锁保护，防止并发读写竞态）"""
    config = load_config()
    cb_config = config.get("circuit_breaker", {})
    if not cb_config.get("enabled", False):
        return

    cb_file = os.path.join(BRIDGE_DIR, "status", "circuit_breaker.json")

    # 文件锁安全读写
    try:
        fd, cb_state = _with_cb_lock(cb_file)
    except TimeoutError:
        return

    circuit = cb_state.get(
        task_type,
        {
            "state": "closed",
            "failure_count": 0,
            "total_count": 0,
            "window_start": datetime.now().isoformat(),
            "last_updated": datetime.now().isoformat(),
        },
    )

    window_minutes = cb_config.get("failure_window_minutes", 30)
    try:
        window_start = datetime.fromisoformat(
            circuit.get("window_start", datetime.now().isoformat())
        )
        if datetime.now() - window_start > timedelta(minutes=window_minutes):
            # 重置窗口
            circuit["failure_count"] = 0
            circuit["total_count"] = 0
            circuit["window_start"] = datetime.now().isoformat()
    except ValueError:
        circuit["window_start"] = datetime.now().isoformat()

    circuit["total_count"] += 1
    if not success:
        circuit["failure_count"] += 1

    # 计算失败率
    failure_rate = circuit["failure_count"] / max(circuit["total_count"], 1)
    circuit["failure_rate"] = round(failure_rate, 2)
    circuit["last_updated"] = datetime.now().isoformat()

    # 检查是否触发熔断
    threshold = cb_config.get("failure_rate_threshold", 0.5)
    min_samples = 3  # 至少3个样本才判断
    if circuit["total_count"] >= min_samples and failure_rate > threshold:
        circuit["state"] = "open"
        circuit["opened_at"] = datetime.now().isoformat()
    elif success and circuit.get("state") == "half_open":
        # 半开状态成功 → 关闭熔断
        circuit["state"] = "closed"
        circuit["failure_count"] = 0
        circuit["total_count"] = 0

    cb_state[task_type] = circuit
    _write_cb_unlock(fd, cb_state)


def write_dead_letter(
    task: dict, errors: list[str], project: str, reason: str = "validation_failed"
):
    """写入死信队列"""
    config = load_config()
    dlq_config = config.get("dead_letter_queue", {})
    if not dlq_config.get("enabled", False):
        return

    dl_dir = os.path.join(BRIDGE_DIR, project, "dead_letter")
    os.makedirs(dl_dir, exist_ok=True)

    task_id = task.get("task_id", uuid.uuid4().hex[:8])
    dl_entry = {
        "_dead_letter": {
            "original_task_id": task_id,
            "failed_at": datetime.now().isoformat(),
            "reason": reason,
            "recovery_suggestion": _suggest_recovery(reason, task.get("retry_count", 0)),
            "retry_count": task.get("retry_count", 0),
            "trace_id": task.get("trace_id", ""),
        },
        "errors": errors,
        "original_payload": task,
        "retry_history": task.get("_retry_history", []),
    }

    filename = f"dlq_{task_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    dl_path = os.path.join(dl_dir, filename)
    with open(dl_path, "w") as f:
        json.dump(dl_entry, f, indent=2, ensure_ascii=False)

    return dl_path


def _suggest_recovery(reason: str, retry_count: int) -> str:
    """根据失败原因和重试次数建议恢复路径"""
    if retry_count < 3:
        return "retry_with_upgrade: 升级模型/增加超时后重试"
    elif "不存在" in reason or "丢失" in reason:
        return "manual_review: 数据源可能不可用，需人工确认"
    else:
        return "permanent_discard: 已达最大重试次数，建议通知上游调整参数"


def validate_task(task: dict) -> list[str]:
    """校验任务 JSON，返回错误列表"""
    config = load_config()
    errors = []

    valid_projects = list(config.get("projects", {}).keys())
    valid_types = config.get("valid_types", [])
    valid_sources = config.get("valid_sources", [])
    valid_priorities = config.get("valid_priorities", [])
    valid_statuses = config.get("valid_statuses", [])
    required_fields = config.get("required_fields", [])

    for field in required_fields:
        if field not in task or task[field] is None:
            errors.append(f"缺少必填字段: {field}")

    if task.get("project") and task["project"] not in valid_projects:
        errors.append(f"无效 project: {task['project']}，可选: {valid_projects}")
    if task.get("type") and task["type"] not in valid_types:
        errors.append(f"无效 type: {task['type']}，可选: {valid_types}")
    if task.get("source") and task["source"] not in valid_sources:
        errors.append(f"无效 source: {task['source']}，可选: {valid_sources}")
    if task.get("priority") and task["priority"] not in valid_priorities:
        errors.append(f"无效 priority: {task['priority']}，可选: {valid_priorities}")
    if task.get("status") and task["status"] not in valid_statuses:
        errors.append(f"无效 status: {task['status']}，可选: {valid_statuses}")

    if task.get("task_id"):
        tid = task["task_id"]
        parts = tid.split("-")

        # 格式1: YYYYMMDD-NNN (标准格式)
        if len(parts) == 2 and len(parts[0]) == 8:
            try:
                datetime.strptime(parts[0], "%Y%m%d")
                int(parts[1])
            except ValueError:
                errors.append(f"task_id 格式错误: {tid}，标准格式 YYYYMMDD-NNN")

        # 格式2: YYYY-MM-DD-HHMM (Marvis 自动任务格式)
        elif len(parts) == 4 and len(parts[0]) == 4:
            try:
                # 将 HHMM 拆分为 HH:MM 以兼容 Python 3.6+
                hhmm = parts[3]
                datetime.strptime(
                    f"{parts[0]}-{parts[1]}-{parts[2]} {hhmm[:2]}:{hhmm[2:]}", "%Y-%m-%d %H:%M"
                )
            except (ValueError, IndexError):
                errors.append(f"task_id 格式错误: {tid}，日期/时间解析失败")

        elif len(parts) == 2:
            # 格式3: YYYYMMDD-XXX (非标准但容忍，如 earnings_20260610)
            if len(parts[0]) == 8:
                try:
                    datetime.strptime(parts[0], "%Y%m%d")
                except ValueError:
                    errors.append(f"task_id 格式错误: {tid}")
            else:
                errors.append(
                    f"task_id 格式错误: {tid}，支持 YYYYMMDD-NNN / YYYY-MM-DD-HHMM / YYYYMMDD-XXX"
                )

        else:
            errors.append(f"task_id 格式错误: {tid}，支持 YYYYMMDD-NNN 或 YYYY-MM-DD-HHMM")

    if task.get("target_dir") and not os.path.isdir(task["target_dir"]):
        errors.append(f"target_dir 不存在: {task['target_dir']}")

    # target_agent 校验：检查是否在 Agent 注册表中
    target_agent = task.get("target_agent", "")
    if target_agent:
        agents_file = os.path.join(BRIDGE_DIR, "status", "agents.json")
        try:
            with open(agents_file) as f:
                agents_data = json.load(f)
            registered_ids = [a["id"] for a in agents_data.get("agents", [])]
            if target_agent not in registered_ids:
                errors.append(f"target_agent 未注册: {target_agent}，可用: {registered_ids}")
        except (FileNotFoundError, json.JSONDecodeError):
            pass  # agents.json 损坏时放过

    # target_agent 与 task_agent_mapping 一致性检查（可选警告）
    if target_agent and target_agent.startswith("qclaw-"):
        bridge_file = os.path.join(BRIDGE_DIR, "status", "bridge.json")
        try:
            with open(bridge_file) as f:
                bridge = json.load(f)
            mapping = bridge.get("routing_rules", {}).get("task_agent_mapping", {})
            task_type = task.get("type", "")
            expected = mapping.get(task_type, "")
            if expected and expected != target_agent:
                # 不阻塞，只输出 warning
                pass  # 允许 override，不报错
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    return errors


def add_trace_span(task: dict, action: str, status: str, agent: str = "workbuddy"):
    """添加 OpenTelemetry trace span"""
    trace_id = task.get("trace_id")
    if not trace_id:
        return

    spans = task.get("_trace_spans", [])
    spans.append(
        {
            "timestamp": datetime.now().isoformat(),
            "trace_id": trace_id,
            "agent": agent,
            "action": action,
            "status": status,
        }
    )
    task["_trace_spans"] = spans


def main():
    if len(sys.argv) < 2:
        print("用法: python3 task_validator.py <task_file.json>")
        print("       python3 task_validator.py --config    # 输出当前配置")
        print("       python3 task_validator.py --check-circuit <type>  # 检查熔断状态")
        print("       python3 task_validator.py --reset-circuit <type>  # 重置熔断器")
        sys.exit(1)

    config = load_config()

    # --config
    if sys.argv[1] == "--config":
        print(json.dumps(config, indent=2, ensure_ascii=False))
        return

    # --check-circuit
    if sys.argv[1] == "--check-circuit":
        task_type = sys.argv[2] if len(sys.argv) > 2 else "all"
        ok, msg = check_circuit_breaker(task_type)
        print(f"{'✅' if ok else '🔴'} {msg}")
        sys.exit(0 if ok else 1)

    # --reset-circuit
    if sys.argv[1] == "--reset-circuit":
        task_type = sys.argv[2] if len(sys.argv) > 2 else "all"
        cb_file = os.path.join(BRIDGE_DIR, "status", "circuit_breaker.json")
        if os.path.exists(cb_file):
            os.remove(cb_file)
            print(f"✅ 熔断器 {task_type} 已重置")
        sys.exit(0)

    task_file = sys.argv[1]
    try:
        with open(task_file) as f:
            task = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"❌ 读取文件失败: {e}")
        sys.exit(1)

    task_id = task.get("task_id", "unknown")
    project = task.get("project", "")
    task_type = task.get("type", "")

    # ====== 熔断器检查 ======
    cb_config = config.get("circuit_breaker", {})
    if cb_config.get("enabled", False) and task_type:
        ok, msg = check_circuit_breaker(task_type)
        if not ok:
            print(f"🔴 熔断拒绝: {msg}")
            # 写入死信队列
            dlq_config = config.get("dead_letter_queue", {})
            if dlq_config.get("enabled", False) and project:
                write_dead_letter(task, [msg], project, "circuit_open")
            sys.exit(3)  # exit code 3 = 熔断拒绝

    # ====== 业务幂等键检查 ======
    idem_config = config.get("idempotency", {})
    if idem_config.get("enabled", False) and idem_config.get("use_business_key", False):
        # 优先使用任务显式设定的幂等键，没有时才从语义派生
        idem_key = task.get("idempotency_key", "")
        if not idem_key:
            idem_key = derive_idempotency_key(task)
        if idem_key:
            # 注入幂等键到任务
            task["idempotency_key"] = idem_key
            ok, msg = check_business_idempotency(idem_key, project)
            if not ok:
                print(f"⏭️  幂等跳过: {msg}")
                sys.exit(2)  # exit code 2 = 幂等跳过

    # ====== 格式校验 ======
    errors = validate_task(task)

    if errors:
        print(f"❌ 校验失败 ({len(errors)} 个错误):")
        for e in errors:
            print(f"  - {e}")

        # 写入死信队列
        dlq_config = config.get("dead_letter_queue", {})
        if dlq_config.get("enabled", False) and project:
            dlq_path = write_dead_letter(task, errors, project, "validation_failed")
            if dlq_path:
                print(f"   📮 已写入死信队列: {dlq_path}")

        # 更新熔断器（失败）
        update_circuit_breaker(task_type, success=False)

        sys.exit(1)
    else:
        print(f"✅ 任务 {task_id} 校验通过")
        print(f"   项目: {project} | 类型: {task_type} | 来源: {task.get('source')}")

        idem_key = task.get("idempotency_key", "")
        if idem_key:
            print(f"   🔑 幂等键: {idem_key}")

        trigger_next = task.get("trigger_next")
        if trigger_next:
            print(f"   🔗 事件驱动: {trigger_next}")

        seq = task.get("sequence")
        if seq:
            print(f"   🔢 序列: {seq.get('index')}/{seq.get('total')}")

        trace_id = task.get("trace_id")
        if trace_id:
            print(f"   🔍 追踪ID: {trace_id}")

        # 更新熔断器（成功）
        update_circuit_breaker(task_type, success=True)

        # 回写含幂等键的任务文件
        with open(task_file, "w") as f:
            json.dump(task, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
