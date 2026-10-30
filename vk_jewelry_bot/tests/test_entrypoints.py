"""Проверки запуска без токена, подключения к ВК и загрузки mediapipe."""
import os
from pathlib import Path
import subprocess
import sys

import pytest


PROJECT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("entry", ["run.py", "bot/app.py", "bot", "bot.app"])
def test_entrypoint_runs_bot_once_from_other_directory(tmp_path, entry):
    # Изолируем внешние сервисы, но выполняем настоящие точки входа проекта.
    script = '''
import runpy
import sys
from types import ModuleType, SimpleNamespace

project, entry = sys.argv[1:]
sys.path.insert(0, project)
class Bot:
    def __init__(self, token):
        self.labeler = SimpleNamespace(load=lambda label: None)
    def run(self):
        print("BOT_STARTED")

vk = ModuleType("vkbottle")
vk.__path__ = []
vk_bot = ModuleType("vkbottle.bot")
vk_bot.Bot = Bot
sys.modules.update({"vkbottle": vk, "vkbottle.bot": vk_bot})
config = ModuleType("bot.config")
config.config = SimpleNamespace(log_level="INFO", vk_token="test", group_id=1)
sys.modules["bot.config"] = config
for name in ("catalog", "common", "photo"):
    module = ModuleType("bot.handlers." + name)
    setattr(module, name + "_labeler", object())
    sys.modules[module.__name__] = module
if entry.endswith(".py"):
    runpy.run_path(project + "/" + entry, run_name="__main__")
else:
    runpy.run_module(entry, run_name="__main__")
'''
    result = subprocess.run(
        [sys.executable, "-c", script, str(PROJECT), entry],
        cwd=tmp_path, capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["BOT_STARTED"]


def test_config_uses_project_env_and_relative_tmp_dir(tmp_path):
    # Копируем конфиг в отдельный проект, не читая настоящий .env разработчика.
    project = tmp_path / "project with spaces"
    bot = project / "bot"
    bot.mkdir(parents=True)
    (bot / "config.py").write_text((PROJECT / "bot/config.py").read_text())
    (project / ".env").write_text(
        "VK_TOKEN=from-file\nVK_GROUP_ID=123\nTMP_DIR=cache/images\n"
    )
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / ".env").write_text("VK_GROUP_ID=999\n")
    env = {k: v for k, v in os.environ.items()
           if k not in {"VK_TOKEN", "VK_GROUP_ID", "TMP_DIR", "LOG_LEVEL", "PYTHON_DOTENV_DISABLED"}}
    env["VK_TOKEN"] = "from-environment"
    script = '''
import runpy, sys
from pathlib import Path
project = Path(sys.argv[1])
c = runpy.run_path(str(project / "bot/config.py"))["config"]
assert c.vk_token == "from-environment"
assert c.group_id == 123
assert c.tmp_dir == project / "cache/images"
assert c.tmp_dir.is_dir()
'''
    result = subprocess.run(
        [sys.executable, "-c", script, str(project)], cwd=elsewhere,
        env=env, capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr
