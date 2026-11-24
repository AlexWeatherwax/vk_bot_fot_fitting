"""Regression checks for the installed SDK's state and logging integration."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

pytest.importorskip("vkbottle")
pytest.importorskip("loguru")


@pytest.fixture
def runtime():
    source = Path(__file__).resolve().parents[1] / "bot" / "runtime.py"
    spec = importlib.util.spec_from_file_location("tested_bot_runtime", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_polling_saves_and_restores_under_state_dir_after_cwd_changes(runtime, tmp_path, monkeypatch):
    state_dir = tmp_path / "writable-state" / "polling"
    first_cwd = tmp_path / "app-cwd"
    second_cwd = tmp_path / "other-cwd"
    first_cwd.mkdir()
    second_cwd.mkdir()
    monkeypatch.chdir(first_cwd)
    polling = runtime.StatefulBotPolling(state_dir, group_id=123, skip_old_events=False)
    polling.save_server_ts({"ts": "saved-ts", "server": "private-server", "key": "private-key"})
    assert polling.ts_state_path == state_dir / "123.json"
    assert json.loads(polling.ts_state_path.read_text()) == {"ts": "saved-ts"}
    assert not list(state_dir.glob("*.tmp"))

    monkeypatch.chdir(second_cwd)
    restarted = runtime.StatefulBotPolling(state_dir, group_id=123, skip_old_events=False)
    assert restarted.restore_server_ts({"ts": "new-ts", "key": "new-key"}) == {
        "ts": "saved-ts", "key": "new-key",
    }
    assert not (first_cwd / ".vkbottle").exists()
    assert not (second_cwd / ".vkbottle").exists()


def test_polling_states_are_isolated_by_group(runtime, tmp_path):
    first = runtime.StatefulBotPolling(tmp_path, group_id=123, skip_old_events=False)
    second = runtime.StatefulBotPolling(tmp_path, group_id=456, skip_old_events=False)
    first.save_server_ts({"ts": "first-ts"})
    second.save_server_ts({"ts": "second-ts"})
    assert first.restore_server_ts({"ts": "fresh"})["ts"] == "first-ts"
    assert second.restore_server_ts({"ts": "fresh"})["ts"] == "second-ts"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["123.json", "456.json"]


@pytest.mark.parametrize("bot_options,expected_skip", [({}, True), ({"skip_old_events": False}, False)])
def test_real_bot_constructor_uses_custom_polling_without_network(runtime, tmp_path, bot_options, expected_skip):
    from vkbottle.bot import Bot

    polling = runtime.StatefulBotPolling(tmp_path, group_id=123, skip_old_events=False)
    bot = Bot(token="fake-test-token", polling=polling, **bot_options)
    assert bot.polling is polling
    assert polling.api is bot.api
    assert polling.group_id == 123
    # Bot owns this policy and overwrites the polling instance's initial value.
    assert polling.skip_old_events is expected_skip
    assert list(tmp_path.iterdir()) == []


def test_polling_state_requires_resolved_group(runtime, tmp_path):
    polling = runtime.StatefulBotPolling(tmp_path)
    with pytest.raises(RuntimeError, match="group_id"):
        _ = polling.ts_state_path
    assert list(tmp_path.iterdir()) == []


def test_info_logging_hides_debug_events_and_exception_locals(runtime):
    # Isolate Loguru's global sinks from the rest of the test process.
    script = '''
import importlib.util
import sys
from loguru import logger
spec = importlib.util.spec_from_file_location("tested_runtime_logging", sys.argv[1])
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)
runtime.configure_logging("INFO")
logger.debug("DEBUG_PRIVATE_EVENT_MARKER")
def fail():
    private_photo = "EXCEPTION_PRIVATE_LOCAL_MARKER"
    raise RuntimeError("safe failure")
try:
    fail()
except RuntimeError:
    logger.exception("Safe upload failure")
'''
    result = subprocess.run(
        [sys.executable, "-c", script, str(Path(runtime.__file__).resolve())],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert "Safe upload failure" in result.stderr
    assert "RuntimeError: safe failure" in result.stderr
    assert "DEBUG_PRIVATE_EVENT_MARKER" not in result.stderr
    assert "EXCEPTION_PRIVATE_LOCAL_MARKER" not in result.stderr
