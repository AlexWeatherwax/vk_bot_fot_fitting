"""Configure a key-only account that can forward only to the local editor.

Run as root on Debian 12: python3 configure_owner_ssh.py --public-key owner.pub
This never accepts a private key or changes another user's SSH credentials.
"""
import argparse
from datetime import datetime, timezone
import fnmatch
import grp
import json
import os
from pathlib import Path
import pwd
import re
import stat
import subprocess
import tempfile

USER = 'imladris-editor'
ACCESS_HOME = Path('/var/lib/imladris-editor')
CONFIG = Path('/etc/ssh/sshd_config')
SSHD = '/usr/sbin/sshd'
BEGIN = '# BEGIN IMLADRIS OWNER SSH'
END = '# END IMLADRIS OWNER SSH'
POLICY = {
    'AuthenticationMethods': 'publickey', 'PubkeyAuthentication': 'yes',
    'PasswordAuthentication': 'no', 'KbdInteractiveAuthentication': 'no',
    'DisableForwarding': 'no', 'AllowTcpForwarding': 'local', 'AllowStreamLocalForwarding': 'no',
    'PermitOpen': '127.0.0.1:8765', 'PermitListen': 'none',
    'AllowAgentForwarding': 'no', 'X11Forwarding': 'no', 'PermitTTY': 'no',
    'PermitTunnel': 'no', 'PermitUserRC': 'no', 'MaxSessions': '0',
}


def run(*args):
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f'Command failed: {args[0]} ({result.returncode})')
    return result.stdout


def ordinary(path, directory=False):
    if path.is_symlink():
        raise ValueError(f'Refusing symbolic link: {path}')
    if path.exists():
        mode = path.stat().st_mode
        if not (stat.S_ISDIR(mode) if directory else stat.S_ISREG(mode)):
            raise ValueError(f'Unexpected file type: {path}')
        if not directory and path.stat().st_nlink != 1:
            raise ValueError(f'Refusing multiply linked file: {path}')


def public_key(path):
    ordinary(path)
    if path.stat().st_size > 16384:
        raise ValueError('Public key file is too large')
    lines = path.read_text(encoding='utf-8-sig').strip().splitlines()
    if len(lines) != 1:
        raise ValueError('Each public key file must contain one public key')
    parts = lines[0].split()
    if len(parts) < 2 or parts[0] not in {
        'ssh-ed25519', 'ssh-rsa', 'ecdsa-sha2-nistp256',
        'ecdsa-sha2-nistp384', 'ecdsa-sha2-nistp521',
    }:
        raise ValueError('Expected an ordinary OpenSSH public key without options')
    key = ' '.join(parts)
    # Normalize BOM/CRLF only in a temporary copy, never overwrite supplied files.
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8') as check:
        check.write(key + '\n')
        check.flush()
        run('ssh-keygen', '-lf', check.name)
    return key


def managed_config(original):
    if original.count(BEGIN) != original.count(END) or original.count(BEGIN) > 1:
        raise ValueError('Existing managed SSH block is malformed')
    if BEGIN in original:
        pattern = re.compile(r'^' + re.escape(BEGIN) + r'\n.*?^' + re.escape(END) + r'\n?', re.M | re.S)
        original, count = pattern.subn('', original)
        if count != 1:
            raise ValueError('Existing managed SSH block is malformed')
    block = '\n'.join([BEGIN, f'Match User {USER}',
                       *(f'    {key} {value}' for key, value in POLICY.items()), END])
    return original.rstrip('\n') + '\n\n' + block + '\n'


def verify_policy(output):
    effective = dict(line.split(None, 1) for line in output.splitlines() if ' ' in line)
    for key, expected in POLICY.items():
        if effective.get(key.lower()) != expected:
            raise RuntimeError(f'Existing SSH rules prevent required policy: {key}')
    if '.ssh/authorized_keys' not in effective.get('authorizedkeysfile', '').split():
        raise RuntimeError('Existing AuthorizedKeysFile does not use this account home')
    if 'allowusers' in effective and not any(
        '@' not in pattern and fnmatch.fnmatchcase(USER, pattern)
        for pattern in effective['allowusers'].split()
    ):
        raise RuntimeError('Existing AllowUsers must explicitly permit imladris-editor')
    if any(fnmatch.fnmatchcase(USER, pattern.split('@', 1)[0])
           for pattern in effective.get('denyusers', '').split()):
        raise RuntimeError('Existing DenyUsers may block imladris-editor')
    if 'allowgroups' in effective and not any(
        fnmatch.fnmatchcase(USER, pattern) for pattern in effective['allowgroups'].split()
    ):
        raise RuntimeError('Existing AllowGroups must permit the imladris-editor group')
    if any(fnmatch.fnmatchcase(USER, pattern) for pattern in effective.get('denygroups', '').split()):
        raise RuntimeError('Existing DenyGroups may block imladris-editor')


def atomic_write(path, content, mode):
    temporary = None
    try:
        fd, temporary = tempfile.mkstemp(prefix='.imladris-', dir=path.parent)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def configure(keys):
    if os.geteuid() != 0:
        raise RuntimeError('Run this helper as root on the VPS')
    for path, directory in [(ACCESS_HOME, True), (ACCESS_HOME / '.ssh', True),
                            (ACCESS_HOME / '.ssh/authorized_keys', False), (CONFIG.parent, True), (CONFIG, False)]:
        ordinary(path, directory)
    run(SSHD, '-t')
    try:
        account = pwd.getpwnam(USER)
    except KeyError:
        try:
            group = grp.getgrnam(USER)
        except KeyError:
            run('groupadd', '--system', USER)
            group = grp.getgrnam(USER)
        run('useradd', '--system', '--gid', str(group.gr_gid), '--create-home',
            '--home-dir', str(ACCESS_HOME), '--shell', '/usr/sbin/nologin', USER)
        account = pwd.getpwnam(USER)
    if (account.pw_dir != str(ACCESS_HOME) or account.pw_shell != '/usr/sbin/nologin'
            or account.pw_uid == 0 or account.pw_gid == 0 or grp.getgrgid(account.pw_gid).gr_name != USER):
        raise RuntimeError('Existing imladris-editor account has unexpected settings')
    run('usermod', '--password', '*', USER)
    for directory in (ACCESS_HOME, ACCESS_HOME / '.ssh'):
        directory.mkdir(mode=0o700, exist_ok=True)
        os.chown(directory, account.pw_uid, account.pw_gid)
        directory.chmod(0o700)

    before = CONFIG.read_bytes()
    updated = managed_config(before.decode('utf-8')).encode()
    mode = stat.S_IMODE(CONFIG.stat().st_mode)
    if updated != before:
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        backup = CONFIG.with_name(CONFIG.name + '.imladris-before-' + stamp)
        with backup.open('xb') as stream:
            os.chmod(backup, 0o600)
            stream.write(before)
        atomic_write(CONFIG, updated, mode)
    try:
        run(SSHD, '-t')
        verify_policy(run(SSHD, '-T', '-C', f'user={USER},host=localhost,addr=127.0.0.1'))
        run('systemctl', 'reload', 'ssh')
    except Exception:
        atomic_write(CONFIG, before, mode)
        run(SSHD, '-t')
        run('systemctl', 'reload', 'ssh')
        raise

    # Only grant keys after the restrictive policy was verified and loaded.
    target = ACCESS_HOME / '.ssh/authorized_keys'
    existing = target.read_text() if target.exists() else ''
    known = {tuple(line.split()[:2]) for line in existing.splitlines()}
    additions = []
    for key in keys:
        identity = tuple(key.split()[:2])
        if identity not in known:
            additions.append(key)
            known.add(identity)
    if additions:
        with target.open('a', encoding='utf-8') as stream:
            stream.write('\n' + '\n'.join(additions) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
    if target.exists():
        os.chown(target, account.pw_uid, account.pw_gid)
        target.chmod(0o600)
    print(json.dumps({'user': USER, 'allowed_destination': '127.0.0.1:8765',
                      'shell_and_sftp': 'disabled', 'public_keys_added': len(additions)}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--public-key', type=Path, action='append', required=True)
    args = parser.parse_args()
    try:
        configure(list(dict.fromkeys(public_key(path) for path in args.public_key)))
    except (ValueError, RuntimeError, OSError) as error:
        parser.exit(1, f'Error: {error}\n')
