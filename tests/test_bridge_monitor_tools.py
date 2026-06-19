"""
bridge_monitor_tools 单元测试
覆盖: get-config, get-task-field, get-fields, enqueue-pending,
      write-dead-letter, check-expired
"""

import json
import sys
import tempfile
import time
from pathlib import Path

import pytest

# 将被测模块加入 path
sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.bridge_monitor_tools import (
    cmd_check_expired,
    cmd_enqueue_pending,
    cmd_get_config,
    cmd_get_fields,
    cmd_get_task_field,
    cmd_write_dead_letter,
    load_config,
)


class TestLoadConfig:
    """load_config() — 安全加载配置，失败返回空字典"""

    def test_loads_valid_config(self, monkeypatch):
        """正常加载 JSON"""
        monkeypatch.setattr(
            "scripts.bridge_monitor_tools.CONFIG_FILE",
            self._make_config({"key": "value"}),
        )
        result = load_config()
        assert result == {"key": "value"}

    def test_missing_file_returns_empty(self, monkeypatch):
        """配置文件不存在→返回空字典"""
        monkeypatch.setattr(
            "scripts.bridge_monitor_tools.CONFIG_FILE",
            Path("/tmp/nonexistent_config.json"),
        )
        result = load_config()
        assert result == {}

    def test_corrupt_json_returns_empty(self, monkeypatch, tmp_path):
        """JSON 损坏→返回空字典"""
        bad = tmp_path / "bad.json"
        bad.write_text("{not valid json")
        monkeypatch.setattr("scripts.bridge_monitor_tools.CONFIG_FILE", bad)
        result = load_config()
        assert result == {}

    def _make_config(self, data: dict) -> Path:
        """创建临时配置文件用于测试"""
        tmp = Path(tempfile.mkstemp(suffix=".json")[1])
        tmp.write_text(json.dumps(data))
        return tmp


class TestGetConfig:
    """cmd_get_config() — 读取嵌套配置键"""

    def test_nested_key(self, monkeypatch, tmp_path):
        """读取嵌套键 automation.scan_interval_seconds"""
        cfg = tmp_path / "config.json"
        cfg.write_text(json.dumps({"automation": {"scan_interval_seconds": 120}}))
        monkeypatch.setattr("scripts.bridge_monitor_tools.CONFIG_FILE", cfg)
        cmd_get_config(["automation.scan_interval_seconds", "30"])

    def test_default_on_missing(self, monkeypatch, tmp_path):
        """键不存在时返回默认值"""
        cfg = tmp_path / "config.json"
        cfg.write_text(json.dumps({}))
        monkeypatch.setattr("scripts.bridge_monitor_tools.CONFIG_FILE", cfg)
        cmd_get_config(["nonexistent.key", "fallback"])


class TestGetTaskField:
    """cmd_get_task_field() — 读取任务 JSON 字段"""

    def test_reads_field(self, capsys, tmp_path):
        """正常读取字段"""
        task = tmp_path / "task.json"
        task.write_text(json.dumps({"type": "data_collection", "project": "claw"}))
        cmd_get_task_field([str(task), "type", "unknown"])
        assert "data_collection" in capsys.readouterr().out

    def test_default_on_missing_field(self, capsys, tmp_path):
        """字段缺失→默认值"""
        task = tmp_path / "task.json"
        task.write_text(json.dumps({"type": "x"}))
        cmd_get_task_field([str(task), "project", "claw"])
        assert "claw" in capsys.readouterr().out

    def test_default_on_missing_file(self, capsys):
        """文件不存在→默认值"""
        cmd_get_task_field(["/tmp/nonexistent.json", "type", "unknown"])
        assert "unknown" in capsys.readouterr().out


class TestGetFields:
    """cmd_get_fields() — 一次读取多个字段"""

    def test_reads_multiple_fields(self, capsys, tmp_path):
        """读取 type, task_id, project 三个字段"""
        task = tmp_path / "task.json"
        task.write_text(
            json.dumps(
                {
                    "type": "data_collection",
                    "task_id": "test-001",
                    "project": "claw",
                }
            )
        )
        cmd_get_fields([str(task), "type", "task_id", "project"])
        out = capsys.readouterr().out.strip()
        assert out == "data_collection test-001 claw"

    def test_missing_file_returns_blanks(self, capsys):
        """不存在的文件→空格分隔的空值，退出码 1"""
        with pytest.raises(SystemExit) as exc:
            cmd_get_fields(["/tmp/nonexistent.json", "type", "task_id"])
        assert exc.value.code == 1
        out = capsys.readouterr().out.strip()
        assert out == ""


class TestEnqueuePending:
    """cmd_enqueue_pending() — 写入 pending 队列并添加时间戳"""

    def test_enqueues_with_timestamp(self, capsys, tmp_path):
        """正常入队，写入 bridge_enqueued_at"""
        task_file = tmp_path / "task.json"
        task_file.write_text(
            json.dumps(
                {
                    "task_id": "test-001",
                    "type": "data_collection",
                    "project": "claw",
                    "target_agent": "workbuddy",
                }
            )
        )
        pending_dir = tmp_path / "pending"

        cmd_enqueue_pending([str(task_file), str(pending_dir)])

        # 验证文件已创建
        dest = pending_dir / "task.json"
        assert dest.exists()

        # 验证时间戳
        data = json.loads(dest.read_text())
        assert "bridge_enqueued_at" in data
        assert isinstance(data["bridge_enqueued_at"], int)
        assert data["bridge_enqueued_at"] <= int(time.time())

        # 验证输出格式
        out = capsys.readouterr().out.strip()
        assert out.startswith("ENQUEUED|")

    def test_missing_task_file(self, tmp_path):
        """任务文件不存在→退出码 1"""
        with pytest.raises(SystemExit) as exc:
            cmd_enqueue_pending(["/tmp/nonexistent.json", str(tmp_path)])
        assert exc.value.code == 1


class TestWriteDeadLetter:
    """cmd_write_dead_letter() — 写入死信队列"""

    def test_writes_dead_letter(self, capsys, tmp_path):
        """正常写入死信"""
        task_file = tmp_path / "task.json"
        task_file.write_text(
            json.dumps(
                {
                    "task_id": "test-fail",
                    "project": "claw",
                    "type": "data_collection",
                }
            )
        )
        dl_base = tmp_path / "dl_base"
        reason = "测试失败原因"

        cmd_write_dead_letter([str(task_file), reason, str(dl_base)])

        # 验证死信文件存在
        dl_dir = dl_base / "claw" / "dead_letter"
        dl_files = list(dl_dir.glob("*.json"))
        assert len(dl_files) == 1

        # 验证内容
        data = json.loads(dl_files[0].read_text())
        assert data["dead_letter_reason"] == reason
        assert data["status"] == "dead_lettered"
        assert "dead_letter_at" in data

    def test_default_project_is_claw(self, capsys, tmp_path):
        """无 project 字段→默认 claw"""
        task_file = tmp_path / "task.json"
        task_file.write_text(json.dumps({"task_id": "test-fail"}))
        dl_base = tmp_path / "dl_base"

        cmd_write_dead_letter([str(task_file), "test", str(dl_base)])

        dl_dir = dl_base / "claw" / "dead_letter"
        assert len(list(dl_dir.glob("*.json"))) == 1


class TestCheckExpired:
    """cmd_check_expired() — 回收过期 pending 任务"""

    def test_no_expiry_for_recent(self, capsys, tmp_path):
        """刚入队的任务不过期"""
        pending_dir = tmp_path / "pending"
        pending_dir.mkdir()
        task = pending_dir / "recent.json"
        task.write_text(
            json.dumps(
                {
                    "task_id": "recent",
                    "project": "claw",
                    "bridge_enqueued_at": int(time.time()),
                }
            )
        )
        dl_base = tmp_path / "dl_base"

        cmd_check_expired([str(pending_dir), "60", str(dl_base)])

        out = capsys.readouterr().out.strip()
        assert "OK|0" in out
        assert task.exists()  # 不过期，不删除

    def test_expired_task_collected(self, capsys, tmp_path):
        """过期任务写入死信并删除"""
        pending_dir = tmp_path / "pending"
        pending_dir.mkdir()
        task = pending_dir / "expired.json"
        task.write_text(
            json.dumps(
                {
                    "task_id": "expired",
                    "project": "claw",
                    "bridge_enqueued_at": int(time.time()) - 3600,  # 1小时前
                }
            )
        )
        dl_base = tmp_path / "dl_base"

        cmd_check_expired([str(pending_dir), "60", str(dl_base)])

        out = capsys.readouterr().out.strip()
        assert "EXPIRED|" in out
        assert not task.exists()  # 已删除

        # 验证死信文件
        dl_dir = dl_base / "claw" / "dead_letter"
        dl_files = list(dl_dir.glob("*.json"))
        assert len(dl_files) == 1
        data = json.loads(dl_files[0].read_text())
        assert "未在 60s 内消费" in data["dead_letter_reason"]

    def test_no_pending_dir_exits_gracefully(self, capsys, tmp_path):
        """pending 目录不存在→正常退出（exit 0）"""
        nonexistent = tmp_path / "nonexistent"
        with pytest.raises(SystemExit) as exc:
            cmd_check_expired([str(nonexistent), "60", str(tmp_path / "dl")])
        assert exc.value.code == 0


class TestIntegration:
    """集成测试：完整任务流转"""

    def test_full_flow(self, capsys, tmp_path):
        """任务：enqueue → check (不回收) → 手动过期 → check (回收)"""
        # 1. 创建任务并入队
        task_file = tmp_path / "task.json"
        task_file.write_text(
            json.dumps(
                {
                    "task_id": "flow-test",
                    "project": "claw",
                    "type": "data_collection",
                    "target_agent": "workbuddy",
                }
            )
        )
        pending_dir = tmp_path / "pending"
        cmd_enqueue_pending([str(task_file), str(pending_dir)])

        # 2. 检查不过期
        dl_base = tmp_path / "dl"
        cmd_check_expired([str(pending_dir), "3600", str(dl_base)])
        out1 = capsys.readouterr().out.strip()
        assert "OK|0" in out1

        # 3. 手动设置 enqueued_at 为 2 小时前（模拟过期）
        pending_file = pending_dir / "task.json"
        data = json.loads(pending_file.read_text())
        data["bridge_enqueued_at"] = int(time.time()) - 7200
        pending_file.write_text(json.dumps(data))

        # 4. 用短 TTL 触发过期回收
        cmd_check_expired([str(pending_dir), "60", str(dl_base)])
        out2 = capsys.readouterr().out.strip()
        assert "EXPIRED|" in out2
        assert not pending_file.exists()  # 已删除


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


class TestWriteDataCollectionResult:
    """cmd_write_data_collection_result() — 写 data_collection 结果 + OCR"""

    def test_writes_result_and_raw(self, tmp_path, capsys):
        """正常写入结果 JSON 并保存 OCR"""
        from scripts.bridge_monitor_tools import cmd_write_data_collection_result

        task = {
            "task_id": "t001",
            "project": "claw",
            "type": "data_collection",
            "title": "测试",
            "source": "marvis",
            "params": {},
        }
        task_file = tmp_path / "task.json"
        task_file.write_text(json.dumps(task))

        result_file = tmp_path / "result.json"
        raw_dir = tmp_path / "raw"

        cmd_write_data_collection_result(
            [
                str(task_file),
                "t001",
                "claw",
                "测试",
                "OCR文本内容",
                "shot.png",
                str(result_file),
                str(raw_dir),
                "2026-06-19 15:00:00",
            ]
        )
        out = capsys.readouterr().out

        assert result_file.exists()
        data = json.loads(result_file.read_text())
        assert data["task_id"] == "t001"
        assert data["status"] == "completed"
        assert data["output"]["ocr_text"] == "OCR文本内容"
        assert data["output"]["screenshot"] == "shot.png"
        assert "RAW_SAVED" in out
        assert list(raw_dir.iterdir())[0].name.startswith("t001_ocr_")

    def test_no_ocr_skips_raw(self, tmp_path, capsys):
        """无 OCR 文本时不保存 raw_data"""
        from scripts.bridge_monitor_tools import cmd_write_data_collection_result

        task = {
            "task_id": "t002",
            "project": "claw",
            "type": "data_collection",
            "title": "无OCR",
            "source": "marvis",
            "params": {},
        }
        task_file = tmp_path / "task.json"
        task_file.write_text(json.dumps(task))

        cmd_write_data_collection_result(
            [
                str(task_file),
                "t002",
                "claw",
                "无OCR",
                "",
                "",
                str(tmp_path / "r.json"),
                str(tmp_path / "raw"),
                "now",
            ]
        )

        assert (tmp_path / "r.json").exists()
        assert not (tmp_path / "raw").exists() or not list((tmp_path / "raw").iterdir())

    def test_missing_task_file(self, capsys):
        """不存在的任务文件应报错退出"""
        from scripts.bridge_monitor_tools import cmd_write_data_collection_result

        with pytest.raises(SystemExit):
            cmd_write_data_collection_result(
                ["/nonexistent", "t", "c", "t", "", "", "/tmp/r", "/tmp/raw", "now"]
            )


class TestWriteSimpleResult:
    """cmd_write_simple_result() — 写简单任务完成状态"""

    def test_writes_result(self, tmp_path, capsys):
        """正常写入结果 JSON"""
        from scripts.bridge_monitor_tools import cmd_write_simple_result

        task = {
            "task_id": "s001",
            "project": "claw",
            "type": "test",
            "title": "简单任务",
            "source": "workbuddy",
            "params": {},
        }
        task_file = tmp_path / "task.json"
        task_file.write_text(json.dumps(task))

        result_file = tmp_path / "result.json"

        cmd_write_simple_result(
            [
                str(task_file),
                "s001",
                "claw",
                "简单任务",
                str(result_file),
                "2026-06-19 15:00:00",
            ]
        )

        assert result_file.exists()
        data = json.loads(result_file.read_text())
        assert data["task_id"] == "s001"
        assert data["status"] == "completed"
        assert data["title"] == "简单任务"
        assert data["source"] == "workbuddy"

    def test_missing_task_file(self, capsys):
        """不存在的任务文件应报错退出"""
        from scripts.bridge_monitor_tools import cmd_write_simple_result

        with pytest.raises(SystemExit):
            cmd_write_simple_result(["/nonexistent", "t", "c", "t", "/tmp/r", "now"])
