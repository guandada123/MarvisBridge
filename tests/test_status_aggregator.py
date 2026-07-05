"""
status_aggregator 单元测试
覆盖: _parse_timestamp / check_marvis / check_claw / send_summary
"""

import json
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.status_aggregator import (
    _parse_timestamp,
    check_claw,
    check_marvis,
    send_summary,
)


class TestParseTimestamp:
    """时间戳解析"""

    def test_unix_timestamp(self):
        ts = _parse_timestamp("1234567890")
        assert ts == 1234567890.0

    def test_unix_float(self):
        ts = _parse_timestamp("1234567890.5")
        assert ts == 1234567890.5

    def test_iso_8601_simple(self):
        ts = _parse_timestamp("2026-06-10T08:30:00")
        assert isinstance(ts, float)
        assert ts > 0

    def test_iso_with_timezone(self):
        ts = _parse_timestamp("2026-06-10T08:30:00+0800")
        assert isinstance(ts, float)

    def test_empty_string_raises(self):
        with pytest.raises((ValueError, TypeError)):
            _parse_timestamp("")

    def test_whitespace_handling(self):
        ts = _parse_timestamp("  1234567890  ")
        assert ts == 1234567890.0


class TestCheckMarvis:
    """Marvis 健康检查"""

    def test_missing_scripts_critical(self, monkeypatch, tmp_path):
        """核心脚本缺失 → critical"""
        # 模拟 MARVIS_DIR 为空目录（没有 core scripts）
        monkeypatch.setattr("scripts.status_aggregator.MARVIS_DIR", tmp_path)
        result = check_marvis()
        assert result["status"] == "critical"
        assert any("缺失" in d for d in result["details"])

    def test_all_scripts_present_no_heartbeat(self, monkeypatch, tmp_path):
        """核心脚本都在但无心跳文件 → critical"""
        for s in [
            "scripts/bridge_monitor.sh",
            "scripts/bridge_notify.py",
            "scripts/health_check.sh",
        ]:
            p = tmp_path / s
            p.parent.mkdir(parents=True, exist_ok=True)
            p.touch()

        monkeypatch.setattr("scripts.status_aggregator.MARVIS_DIR", tmp_path)
        result = check_marvis()
        assert result["status"] == "critical"
        assert any("缺失" in d for d in result["details"])

    def test_healthy_with_recent_heartbeat(self, monkeypatch, tmp_path):
        """核心脚本存在 + 心跳正常 → healthy"""
        for s in [
            "scripts/bridge_monitor.sh",
            "scripts/bridge_notify.py",
            "scripts/health_check.sh",
        ]:
            p = tmp_path / s
            p.parent.mkdir(parents=True, exist_ok=True)
            p.touch()

        # 写入最近的心跳
        hb = tmp_path / "status" / "heartbeat"
        hb.parent.mkdir(parents=True, exist_ok=True)
        hb.write_text(f"{time.time():.0f}")

        monkeypatch.setattr("scripts.status_aggregator.MARVIS_DIR", tmp_path)
        result = check_marvis()
        assert result["status"] == "healthy"

    def test_stale_heartbeat_warning(self, monkeypatch, tmp_path):
        """心跳过旧 → warning"""
        for s in [
            "scripts/bridge_monitor.sh",
            "scripts/bridge_notify.py",
            "scripts/health_check.sh",
        ]:
            p = tmp_path / s
            p.parent.mkdir(parents=True, exist_ok=True)
            p.touch()

        # 写入 10 分钟前的心跳
        hb = tmp_path / "status" / "heartbeat"
        hb.parent.mkdir(parents=True, exist_ok=True)
        hb.write_text(f"{time.time() - 600:.0f}")

        monkeypatch.setattr("scripts.status_aggregator.MARVIS_DIR", tmp_path)
        result = check_marvis()
        assert result["status"] == "warning"
        assert any("过旧" in d for d in result["details"])


class TestCheckClaw:
    """Claw 心跳检查"""

    def test_no_heartbeat_file(self, monkeypatch, tmp_path):
        """心跳文件不存在 → warning"""
        monkeypatch.setattr("scripts.status_aggregator.CLAW_HEARTBEAT", tmp_path / "nonexistent.json")
        result = check_claw()
        assert result["status"] == "warning"
        assert any("未生成" in d for d in result["details"])

    def test_healthy_heartbeat(self, monkeypatch, tmp_path):
        """心跳正常 → healthy"""
        hb_file = tmp_path / "heartbeat.json"
        hb_file.write_text(json.dumps({
            "last_heartbeat": "2026-06-10T08:30:00",
            "healthy": True,
            "dependencies": {"database": True, "api": True},
        }))
        monkeypatch.setattr("scripts.status_aggregator.CLAW_HEARTBEAT", hb_file)
        result = check_claw()
        assert result["status"] == "healthy"

    def test_unhealthy_heartbeat(self, monkeypatch, tmp_path):
        """心跳 unhealthy → critical"""
        hb_file = tmp_path / "heartbeat.json"
        hb_file.write_text(json.dumps({
            "last_heartbeat": "2026-06-10T08:30:00",
            "healthy": False,
            "dependencies": {"database": False},
        }))
        monkeypatch.setattr("scripts.status_aggregator.CLAW_HEARTBEAT", hb_file)
        result = check_claw()
        assert result["status"] == "critical"

    def test_corrupt_heartbeat(self, monkeypatch, tmp_path):
        """心跳文件损坏 → critical"""
        hb_file = tmp_path / "heartbeat.json"
        hb_file.write_text("{broken")
        monkeypatch.setattr("scripts.status_aggregator.CLAW_HEARTBEAT", hb_file)
        result = check_claw()
        assert result["status"] == "critical"


class TestSendSummary:
    """飞书推送"""

    def test_no_webhook_skips(self, monkeypatch):
        monkeypatch.setattr("scripts.status_aggregator.FEISHU_WEBHOOK", "")
        assert send_summary([]) is False

    def test_no_critical_uses_blue(self, monkeypatch):
        monkeypatch.setattr("scripts.status_aggregator.FEISHU_WEBHOOK", "https://example.com/webhook")

        sent_payload = {}

        class MockContext:
            def __enter__(self_):
                return self_
            def __exit__(self_, *args):
                pass
            def read(self_):
                return b'{"code": 0}'

        def mock_urlopen(req, timeout=10):
            sent_payload["url"] = req.full_url
            sent_payload["data"] = json.loads(req.data)
            return MockContext()

        monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)
        results = [{"name": "Claw", "status": "healthy"}, {"name": "MarvisBridge", "status": "warning"}]
        assert send_summary(results) is True
        assert sent_payload["data"]["card"]["header"]["template"] == "blue"

    def test_with_critical_uses_red(self, monkeypatch):
        """"有 critical 状态 → 红色模板"""
        monkeypatch.setattr("scripts.status_aggregator.FEISHU_WEBHOOK", "https://example.com/webhook")

        sent_data = {}

        class MockContext:
            def __enter__(self_):
                return self_
            def __exit__(self_, *args):
                pass
            def read(self_):
                return b'{"code": 0}'

        def mock_urlopen(req, timeout=10):
            sent_data["data"] = json.loads(req.data)
            return MockContext()

        monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)
        results = [{"name": "MarvisBridge", "status": "critical"}]
        assert send_summary(results) is True
        assert sent_data["data"]["card"]["header"]["template"] == "red"


class TestCheckQts:
    """QTS 健康检查"""

    def test_no_compose_file(self, monkeypatch, tmp_path):
        """docker-compose.yml 不存在 → warning"""
        monkeypatch.setattr("scripts.status_aggregator.HOME", tmp_path)
        from scripts.status_aggregator import check_qts
        result = check_qts()
        assert result["status"] == "warning"
        assert any("缺失" in d for d in result["details"])

    def test_no_services_running(self, monkeypatch, tmp_path):
        """compose 文件存在但所有服务未运行"""
        qts_dir = tmp_path / "WorkBuddy" / "QuantTradingSystem"
        qts_dir.mkdir(parents=True)
        (qts_dir / "docker-compose.yml").touch()

        monkeypatch.setattr("scripts.status_aggregator.HOME", tmp_path)

        def mock_urlopen(req, timeout=3):
            raise Exception("not running")
        monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)

        from scripts.status_aggregator import check_qts
        result = check_qts()
        assert result["status"] == "warning"
