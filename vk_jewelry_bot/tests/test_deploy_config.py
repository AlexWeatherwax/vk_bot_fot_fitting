"""Prevent accepting credentials that systemd would interpret differently."""
import importlib.util
from pathlib import Path

import pytest


SOURCE = Path(__file__).resolve().parents[1] / 'deploy/check_config.py'
spec = importlib.util.spec_from_file_location('deploy_check_config', SOURCE)
config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(config)


def test_literal_values_match_systemd_without_shell_or_variable_expansion():
    raw = b'# comment\r\nEDITOR_PASSWORD=Abc123456789!#$()=xxx\r\nEDITOR_USER=author\r\n'
    assert config.parse_config(raw, 'editor') == {
        'EDITOR_PASSWORD': 'Abc123456789!#$()=xxx', 'EDITOR_USER': 'author'}


@pytest.mark.parametrize('raw', [
    b'\xef\xbb\xbfVK_GROUP_ID=1', b'VK_GROUP_ID=1 # comment',
    b'VK_GROUP_ID="1"', b'VK_GROUP_ID=1\\2', b'VK_GROUP_ID=1 ',
    b'export VK_GROUP_ID=1', b'VK_GROUP_ID=1\nVK_GROUP_ID=2',
    b'VK_GROUP_ID=1\x00', b'# comment\x00\nVK_GROUP_ID=1',
    'VK_GROUP_ID=1\u2028'.encode(),
])
def test_ambiguous_environment_file_is_rejected_without_echoing_contents(raw):
    with pytest.raises(ValueError) as error:
        config.parse_config(raw, 'bot')
    assert raw.decode('utf-8', errors='replace') not in str(error.value)


def test_qa_password_cannot_be_activated():
    with pytest.raises(ValueError, match='новый EDITOR_PASSWORD'):
        config.validate({'VK_TOKEN': 'x' * 40, 'VK_GROUP_ID': '1'},
                        {'EDITOR_USER': 'author', 'EDITOR_PASSWORD': 'qa-jewelry-editor-password'})


def test_filled_literal_configuration_can_be_activated():
    config.validate({'VK_TOKEN': 'x' * 40, 'VK_GROUP_ID': '123'},
                    {'EDITOR_USER': 'author', 'EDITOR_PASSWORD': 'owner-password-example-2026'})
