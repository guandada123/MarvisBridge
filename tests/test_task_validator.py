"""
task_validator 单元测试
覆盖: 校验逻辑/幂等键/熔断器/死信/配置加载
"""

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.task_validator import (
    _fallback_config,
    _suggest_recovery,
    add_trace_span,
    check_business_idempotency,
    check_circuit_breaker,
    derive_idempotency_key,
    load_config,
    update_circuit_breaker,
    validate_task,
    write_dead_letter,
)


class TestConfig:
    """配置加载"""

    def test_load_config_returns_dict(self, monkeypatch, tmp_path):
        cf = tmp_path / "config.json"
        cf.write_text('{"key": "val"}')
        monkeypatch.setattr("scripts.task_validator.CONFIG_FILE", str(cf))
        assert load_config() == {"key": "val"}

    def test_missing_file_returns_fallback(self, monkeypatch):
        monkeypatch.setattr("scripts.task_validator.CONFIG_FILE", "/nonexistent.json")
        result = load_config()
        assert "valid_types" in result
        assert "required_fields" in result

    def test_corrupt_json_returns_fallback(self, monkeypatch, tmp_path):
        cf = tmp_path / "config.json"
        cf.write_text("{broken}")
        monkeypatch.setattr("scripts.task_validator.CONFIG_FILE", str(cf))
        result = load_config()
        assert "valid_types" in result

    def test_fallback_config_structure(self):
        cfg = _fallback_config()
        assert "projects" in cfg
        assert "claw" in cfg["projects"]
        assert "valid_types" in cfg
        assert "idempotency" in cfg
        assert "circuit_breaker" in cfg


class TestDeriveIdempotencyKey:
    """幂等键推导"""

    def test_standard_yyyymmdd_nnn_format(self):
        task = {"project": "claw", "type": "data_collection", "task_id": "20260610-001"}
        key = derive_idempotency_key(task)
        assert key.startswith("claw:data_collection:20260610:")

    def test_marvis_auto_format(self):
        task = {"project": "quant", "type": "code_review", "task_id": "2026-06-10-0830"}
        key = derive_idempotency_key(task)
        assert key.startswith("quant:code_review:20260610:")

    def test_with_trigger_next_as_business_id(self):
        task = {
            "project": "claw",
            "type": "data_analysis",
            "task_id": "20260610-001",
            "trigger_next": "market_snapshot_20260610",
        }
        key = derive_idempotency_key(task)
        assert "market_snapshot_20260610" in key

    def test_with_sequence_group(self):
        task = {
            "project": "claw",
            "type": "report",
            "task_id": "20260610-001",
            "sequence": {"group": "weekly_report_2026W24", "index": 1, "total": 5},
        }
        key = derive_idempotency_key(task)
        assert "weekly_report_2026W24" in key

    def test_fallback_to_title(self):
        task = {
            "project": "shared",
            "type": "maintenance",
            "task_id": "20260610-001",
            "title": "Clean up old logs",
        }
        key = derive_idempotency_key(task)
        assert "Clean_up_old_logs" in key

    def test_idempotency_disabled(self, monkeypatch):
        monkeypatch.setattr(
            "scripts.task_validator.load_config",
            lambda: {"idempotency": {"use_business_key": False}},
        )
        task = {"task_id": "20260610-001"}
        assert derive_idempotency_key(task) == ""

    def test_unknown_task_id_format(self):
        task = {"project": "claw", "type": "test", "task_id": "abc"}
        key = derive_idempotency_key(task)
        # "abc" 不含 "-"，date_part 回退为 "unknown"
        assert key == "claw:test:unknown:unknown"


class TestValidateTask:
    """任务校验"""

    @pytest.fixture
    def config(self):
        return _fallback_config()

    def test_passes_valid_task(self):
        task = {
            "task_id": "20260610-001",
            "project": "claw",
            "type": "data_collection",
            "source": "marvis",
            "title": "Test task",
        }
        errors = validate_task(task)
        assert errors == []

    def test_missing_required_fields(self):
        task = {"task_id": "20260610-001"}
        errors = validate_task(task)
        missing = [e for e in errors if "缺少必填字段" in e]
        assert len(missing) >= 1

    def test_invalid_project(self):
        task = {
            "task_id": "20260610-001",
            "project": "nonexistent",
            "type": "data_collection",
            "source": "marvis",
            "title": "Test",
        }
        errors = validate_task(task)
        assert any("无效 project" in e for e in errors)

    def test_invalid_type(self):
        task = {
            "task_id": "20260610-001",
            "project": "claw",
            "type": "black_hole_operation",
            "source": "marvis",
            "title": "Test",
        }
        errors = validate_task(task)
        assert any("无效 type" in e for e in errors)

    def test_invalid_source(self):
        task = {
            "task_id": "20260610-001",
            "project": "claw",
            "type": "data_collection",
            "source": "alien",
            "title": "Test",
        }
        errors = validate_task(task)
        assert any("无效 source" in e for e in errors)

    def test_invalid_priority(self):
        task = {
            "task_id": "20260610-001",
            "project": "claw",
            "type": "data_collection",
            "source": "marvis",
            "title": "Test",
            "priority": "critical",
        }
        errors = validate_task(task)
        assert any("无效 priority" in e for e in errors)

    def test_bad_task_id_format(self):
        task = {
            "task_id": "not-a-valid-id",
            "project": "claw",
            "type": "data_collection",
            "source": "marvis",
            "title": "Test",
        }
        errors = validate_task(task)
        assert any("task_id 格式错误" in e for e in errors)

    def test_valid_standard_task_id(self):
        """标准格式 YYYYMMDD-NNN 通过"""
        task = {
            "task_id": "20260610-001",
            "project": "claw",
            "type": "data_collection",
            "source": "marvis",
            "title": "Test",
        }
        errors = validate_task(task)
        assert all("task_id" not in e for e in errors)

    def test_rejects_non_numeric_xxx(self):
        """非数字的 XXX 会被格式1拒绝（int() 失败）"""
        task = {
            "task_id": "20260610-earnings",
            "project": "claw",
            "type": "data_collection",
            "source": "marvis",
            "title": "Test",
        }
        errors = validate_task(task)
        assert any("task_id 格式错误" in e for e in errors)

    def test_short_yyyymmdd_xxx_invalid_date(self):
        """格式3但日期无效"""
        task = {
            "task_id": "20269999-earnings",
            "project": "claw",
            "type": "data_collection",
            "source": "marvis",
            "title": "Test",
        }
        errors = validate_task(task)
        assert any("task_id 格式错误" in e for e in errors)


class TestSuggestRecovery:
    """恢复建议"""

    def test_under_3_retries(self):
        assert "retry_with_upgrade" in _suggest_recovery("some_error", 0)
        assert "retry_with_upgrade" in _suggest_recovery("some_error", 2)

    def test_not_found_after_3_retries(self):
        result = _suggest_recovery("文件不存在", 3)
        assert "manual_review" in result

    def test_permanent_discard_after_3_retries(self):
        result = _suggest_recovery("connection_refused", 3)
        assert "permanent_discard" in result


class TestAddTraceSpan:
    """追踪 span"""

    def test_adds_span(self):
        task = {"trace_id": "abc123"}
        add_trace_span(task, "validate", "ok")
        assert len(task["_trace_spans"]) == 1
        assert task["_trace_spans"][0]["action"] == "validate"
        assert task["_trace_spans"][0]["status"] == "ok"

    def test_no_trace_id_skips(self):
        task = {}
        add_trace_span(task, "validate", "ok")
        assert "_trace_spans" not in task

    def test_appends_multiple_spans(self):
        task = {"trace_id": "abc123"}
        add_trace_span(task, "validate", "ok")
        add_trace_span(task, "execute", "ok")
        assert len(task["_trace_spans"]) == 2


class TestCheckBusinessIdempotency:
    """业务幂等性检查"""

    def test_empty_key_passes(self):
        ok, msg = check_business_idempotency("", "claw")
        assert ok is True
        assert "无业务幂等键" in msg

    def test_no_done_dir_passes(self, monkeypatch, tmp_path):
        monkeypatch.setattr("scripts.task_validator.BRIDGE_DIR", str(tmp_path))
        ok, msg = check_business_idempotency("claw:data_collection:20260610:test", "claw")
        assert ok is True

    def test_detects_duplicate_in_done(self, monkeypatch, tmp_path):
        done_dir = tmp_path / "claw" / "done"
        done_dir.mkdir(parents=True)
        (done_dir / "done_001.json").write_text(
            json.dumps({"idempotency_key": "claw:data_collection:20260610:test"})
        )
        monkeypatch.setattr("scripts.task_validator.BRIDGE_DIR", str(tmp_path))
        ok, msg = check_business_idempotency("claw:data_collection:20260610:test", "claw")
        assert ok is False
        assert "已归档" in msg

    def test_detects_duplicate_in_tasks(self, monkeypatch, tmp_path):
        tasks_dir = tmp_path / "claw" / "tasks"
        tasks_dir.mkdir(parents=True)
        (tasks_dir / "task_001.json").write_text(
            json.dumps({"idempotency_key": "claw:data_collection:20260610:test"})
        )
        monkeypatch.setattr("scripts.task_validator.BRIDGE_DIR", str(tmp_path))
        ok, msg = check_business_idempotency("claw:data_collection:20260610:test", "claw")
        assert ok is False
        assert "已在队列中" in msg

    def test_skips_template_json(self, monkeypatch, tmp_path):
        tasks_dir = tmp_path / "claw" / "tasks"
        tasks_dir.mkdir(parents=True)
        (tasks_dir / "template.json").write_text(
            json.dumps({"idempotency_key": "claw:data_collection:20260610:test"})
        )
        monkeypatch.setattr("scripts.task_validator.BRIDGE_DIR", str(tmp_path))
        ok, msg = check_business_idempotency("claw:data_collection:20260610:test", "claw")
        assert ok is True


class TestCircuitBreaker:
    """熔断器 — 绕过文件锁直写测试"""

    def test_circuit_closed(self, monkeypatch, tmp_path):
        status_dir = tmp_path / "status"
        status_dir.mkdir()
        cb_file = status_dir / "circuit_breaker.json"
        cb_file.write_text("{}")
        monkeypatch.setattr("scripts.task_validator.BRIDGE_DIR", str(tmp_path))
        monkeypatch.setattr(
            "scripts.task_validator.load_config",
            lambda: {
                "circuit_breaker": {
                    "enabled": True,
                    "failure_window_minutes": 30,
                    "failure_rate_threshold": 0.5,
                    "circuit_open_minutes": 30,
                },
            },
        )

        # patch _with_cb_lock to read/write our file
        def mock_lock(cb_path, mode="r"):
            fd = os.open(str(cb_file), os.O_RDWR | os.O_CREAT, 0o644)
            data = json.loads(os.read(fd, 4096).decode() or "{}")
            return fd, data

        monkeypatch.setattr("scripts.task_validator._with_cb_lock", mock_lock)
        monkeypatch.setattr("scripts.task_validator._write_cb_unlock", lambda fd, data: None)

        ok, msg = check_circuit_breaker("data_collection")
        assert ok is True
        assert "关闭" in msg

    def test_disabled_cb_passes(self, monkeypatch):
        monkeypatch.setattr(
            "scripts.task_validator.load_config",
            lambda: {"circuit_breaker": {"enabled": False}},
        )
        ok, msg = check_circuit_breaker("anything")
        assert ok is True
        assert "未启用" in msg


class TestWriteDeadLetter:
    """死信队列写入"""

    def test_writes_dlq(self, monkeypatch, tmp_path):
        monkeypatch.setattr("scripts.task_validator.BRIDGE_DIR", str(tmp_path))
        monkeypatch.setattr(
            "scripts.task_validator.load_config",
            lambda: {"dead_letter_queue": {"enabled": True, "retention_days": 30}},
        )
        task = {"task_id": "test-001", "retry_count": 1}
        path = write_dead_letter(task, ["error 1"], "claw", "validation_failed")
        assert path is not None
        assert os.path.exists(path)
        with open(path) as f:
            entry = json.load(f)
        assert entry["_dead_letter"]["reason"] == "validation_failed"
        assert entry["errors"] == ["error 1"]

    def test_disabled_dlq_skips(self, monkeypatch, tmp_path):
        monkeypatch.setattr("scripts.task_validator.BRIDGE_DIR", str(tmp_path))
        monkeypatch.setattr(
            "scripts.task_validator.load_config",
            lambda: {"dead_letter_queue": {"enabled": False}},
        )
        path = write_dead_letter({}, ["error"], "claw")
        assert path is None


class TestUpdateCircuitBreaker:
    """熔断器更新"""

    def test_disabled_does_nothing(self, monkeypatch):
        monkeypatch.setattr(
            "scripts.task_validator.load_config",
            lambda: {"circuit_breaker": {"enabled": False}},
        )
        # 不抛异常就算过
        update_circuit_breaker("data_collection", True)
