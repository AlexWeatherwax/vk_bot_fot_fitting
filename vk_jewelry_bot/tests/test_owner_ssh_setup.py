"""Check owner SSH policy generation and rollback without modifying the host."""
import importlib.util
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

SOURCE = Path(__file__).resolve().parents[1] / 'deploy/configure_owner_ssh.py'
spec = importlib.util.spec_from_file_location('configure_owner_ssh', SOURCE)
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


def effective(**changes):
    values = {key.lower(): value for key, value in helper.POLICY.items()}
    values['authorizedkeysfile'] = '.ssh/authorized_keys .ssh/authorized_keys2'
    values.update(changes)
    return '\n'.join(key + ' ' + value for key, value in values.items())


def test_managed_block_stays_last_and_repeated_configuration_is_identical():
    original = 'Port 22\nPermitRootLogin prohibit-password\nMatch User another\n    PermitTTY no\n'
    first = helper.managed_config(original)
    assert first.startswith(original)
    assert first.endswith(helper.END + '\n')
    assert first.count(helper.BEGIN) == 1
    assert helper.managed_config(first) == first


def test_existing_managed_block_is_moved_to_end_preserving_later_rules():
    original = helper.managed_config('Port 22\n') + 'Match User another\n    PermitTTY no\n'
    updated = helper.managed_config(original)
    assert 'Match User another\n    PermitTTY no\n' in updated
    assert updated.index('Match User another') < updated.index(helper.BEGIN)
    assert updated.count(helper.BEGIN) == 1


@pytest.mark.parametrize('text', [helper.BEGIN, helper.END, helper.BEGIN + '\n' + helper.BEGIN + '\n' + helper.END])
def test_malformed_managed_block_is_refused(text):
    with pytest.raises(ValueError):
        helper.managed_config(text)


@pytest.mark.parametrize('changes', [
    {'allowtcpforwarding': 'yes'}, {'disableforwarding': 'yes'}, {'permitlisten': 'any'}, {'maxsessions': '10'},
    {'authorizedkeysfile': '/custom/keys'}, {'allowusers': 'root'},
    {'denyusers': 'imladris-*'}, {'allowgroups': 'root'}, {'denygroups': 'imladris-*'},
])
def test_other_ssh_rules_cannot_silently_weaken_or_block_the_account(changes):
    with pytest.raises(RuntimeError):
        helper.verify_policy(effective(**changes))


def test_expected_effective_policy_is_accepted():
    helper.verify_policy(effective(allowusers='root imladris-editor', allowgroups='imladris-editor'))


def test_public_key_validation_accepts_bom_and_preserves_supplied_file(tmp_path):
    key = tmp_path / 'test-key'
    subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-f', str(key), '-N', ''], check=True)
    public = key.with_suffix('.pub')
    content = b'\xef\xbb\xbf' + public.read_bytes().rstrip() + b'\r\n'
    public.write_bytes(content)
    assert helper.public_key(public).startswith('ssh-ed25519 ')
    assert public.read_bytes() == content


def test_symlink_and_private_key_header_are_rejected(tmp_path):
    target = tmp_path / 'not-a-public-key'
    target.write_text('-----BEGIN OPENSSH PRIVATE KEY-----\ndummy')
    link = tmp_path / 'link.pub'
    link.symlink_to(target)
    with pytest.raises(ValueError, match='symbolic'):
        helper.public_key(link)
    with pytest.raises(ValueError):
        helper.public_key(target)


def test_failed_policy_validation_restores_original_config_before_granting_key(tmp_path, monkeypatch):
    config = tmp_path / 'sshd_config'
    before = b'Port 22\nPermitRootLogin prohibit-password\n'
    config.write_bytes(before)
    home = tmp_path / 'owner-home'
    monkeypatch.setattr(helper, 'CONFIG', config)
    monkeypatch.setattr(helper, 'ACCESS_HOME', home)
    monkeypatch.setattr(helper.os, 'geteuid', lambda: 0)
    monkeypatch.setattr(helper.os, 'chown', lambda *args: None)
    monkeypatch.setattr(helper.pwd, 'getpwnam', lambda _: SimpleNamespace(
        pw_dir=str(home), pw_shell='/usr/sbin/nologin', pw_uid=1001, pw_gid=1001))
    monkeypatch.setattr(helper.grp, 'getgrgid', lambda _: SimpleNamespace(gr_name=helper.USER))
    calls = []

    def command(*args):
        calls.append(args)
        return effective(allowtcpforwarding='yes') if '-T' in args else ''

    monkeypatch.setattr(helper, 'run', command)
    with pytest.raises(RuntimeError, match='AllowTcpForwarding'):
        helper.configure(['ssh-ed25519 AAAA dummy'])
    assert config.read_bytes() == before
    assert not (home / '.ssh/authorized_keys').exists()
    assert list(tmp_path.glob('sshd_config.imladris-before-*'))
    assert calls[-1] == ('systemctl', 'reload', 'ssh')
