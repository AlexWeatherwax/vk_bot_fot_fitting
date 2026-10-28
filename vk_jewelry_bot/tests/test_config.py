"""Проверки конфигурации без настоящего .env и без обращения к VK."""
import importlib.util
import os
import sys
import tempfile
import types
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock, patch


CONFIG_PATH = Path(__file__).resolve().parents[1] / "bot" / "config.py"


@contextmanager
def loaded_config(extra_environment=None):
    # Изолируем загрузку .env, чтобы тесты не читали локальные токены.
    dotenv_module = types.ModuleType("dotenv")
    dotenv_module.load_dotenv = Mock()
    name = "_config_under_test"
    spec = importlib.util.spec_from_file_location(name, CONFIG_PATH)
    module = importlib.util.module_from_spec(spec)
    environment = {"VK_TOKEN": "test-token", "VK_GROUP_ID": "123"}
    environment.update(extra_environment or {})
    with patch.dict(os.environ, environment, clear=True), patch.dict(
        sys.modules, {"dotenv": dotenv_module, name: module}
    ):
        spec.loader.exec_module(module)
        yield module, dotenv_module.load_dotenv


class ConfigTests(unittest.TestCase):
    def test_env_file_is_anchored_to_project_not_working_directory(self):
        with loaded_config() as (module, load_dotenv):
            load_dotenv.assert_called_once_with(CONFIG_PATH.parent.parent / ".env")
            self.assertEqual(module.config.group_id, 123)
            self.assertEqual(module.config.log_level, "INFO")

    def test_configuration_does_not_create_unused_temporary_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            unused = Path(directory) / "unused"
            with loaded_config({"TMP_DIR": str(unused)}) as (module, _):
                self.assertFalse(unused.exists())
                self.assertFalse(hasattr(module.config, "tmp_dir"))

    def test_missing_token_has_actionable_error(self):
        with loaded_config() as (module, _):
            del os.environ["VK_TOKEN"]
            with self.assertRaisesRegex(RuntimeError, "VK_TOKEN"):
                module.load_config()

    def test_missing_group_has_actionable_error(self):
        with loaded_config() as (module, _):
            del os.environ["VK_GROUP_ID"]
            with self.assertRaisesRegex(RuntimeError, "VK_GROUP_ID"):
                module.load_config()

    def test_log_level_is_read_from_environment(self):
        with loaded_config({"LOG_LEVEL": "DEBUG"}) as (module, _):
            self.assertEqual(module.config.log_level, "DEBUG")


if __name__ == "__main__":
    unittest.main()
