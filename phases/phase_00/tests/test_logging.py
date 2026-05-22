"""Phase 0 — persistent log files."""

import json
from pathlib import Path

import pytest

from phases.phase_00.logging_setup import configure_logging, get_log_paths, get_logger


@pytest.fixture
def temp_logs(tmp_path, monkeypatch):
    log_dir = tmp_path / "test_logs"
    monkeypatch.setenv("LOG_DIR", str(log_dir))
    monkeypatch.setenv("LOG_FILE_NAME", "swiggy-talk.log")
    monkeypatch.setenv("LOG_ERRORS_FILE_NAME", "errors.log")
    monkeypatch.setenv("ORDER_ENABLED", "false")
    monkeypatch.setenv("EVAL_SUITE_PASSED", "false")

    from phases.phase_00 import config as config_mod
    from phases.phase_00 import logging_setup as logging_mod

    config_mod.get_settings.cache_clear()
    logging_mod._CONFIGURED = False
    configure_logging()
    yield log_dir
    logging_mod._CONFIGURED = False
    config_mod.get_settings.cache_clear()


def test_log_files_created_on_configure(temp_logs):
    paths = get_log_paths()
    assert Path(paths["app_log"]).exists()
    assert Path(paths["errors_log"]).exists()


def test_info_written_to_app_log(temp_logs):
    log = get_logger("test")
    log.info("test_event", detail="phase0")
    app_log = temp_logs / "swiggy-talk.log"
    content = app_log.read_text()
    assert "test_event" in content
    line = [ln for ln in content.strip().splitlines() if "test_event" in ln][-1]
    parsed = json.loads(line)
    assert parsed["event"] == "test_event"
    assert parsed["detail"] == "phase0"


def test_warning_written_to_errors_log(temp_logs):
    log = get_logger("test")
    log.warning("test_warning_event", reason="simulated_failure")
    errors_log = temp_logs / "errors.log"
    content = errors_log.read_text()
    assert "test_warning_event" in content
    assert '"level": "warning"' in content or '"level":"warning"' in content.replace(" ", "")
