"""Validate a literal subset of systemd EnvironmentFile without logging secrets."""
from pathlib import Path
import re
import sys


def parse_config(raw: bytes, name: str) -> dict[str, str]:
    if raw.startswith(b'\xef\xbb\xbf'):
        raise ValueError(f'Сохраните {name}.env в UTF-8 без BOM.')
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError:
        raise ValueError(f'Сохраните {name}.env в UTF-8.') from None
    if any((ord(char) < 32 and char not in '\r\n') or ord(char) == 127 for char in text):
        raise ValueError(f'{name}.env содержит управляющие символы.')
    values = {}
    for number, raw_line in enumerate(text.split('\n'), 1):
        line = raw_line.removesuffix('\r')
        if not line or line.startswith('#'):
            continue
        match = re.fullmatch(r'''([A-Z_][A-Z_0-9]*)=([^\s"'\\]*)''', line)
        if not match or any(ord(char) < 32 or ord(char) == 127 or char == '\ufeff' for char in line):
            raise ValueError(f'{name}.env, строка {number}: используйте KEY=VALUE без пробелов, кавычек и обратных слешей; комментарий — отдельной строкой с #.')
        key, value = match.groups()
        if key in values:
            raise ValueError(f'{name}.env содержит повторяющийся ключ {key}.')
        values[key] = value
    return values


def validate(bot: dict[str, str], editor: dict[str, str]) -> None:
    token = bot.get('VK_TOKEN', '')
    if len(token) < 20 or token in {'offline-validation-placeholder', 'your_vk_token_here'}:
        raise ValueError('Заполните настоящий VK_TOKEN в bot.env.')
    group = bot.get('VK_GROUP_ID', '')
    if not re.fullmatch(r'[0-9]+', group) or int(group) <= 0:
        raise ValueError('VK_GROUP_ID должен быть положительным числом без минуса.')
    user = editor.get('EDITOR_USER', '')
    if not user or ':' in user:
        raise ValueError('Заполните EDITOR_USER в editor.env без двоеточия.')
    password = editor.get('EDITOR_PASSWORD', '')
    if len(password) < 16 or password == 'qa-jewelry-editor-password':
        raise ValueError('Задайте новый EDITOR_PASSWORD не короче 16 символов в editor.env.')


def main() -> int:
    directory = Path('/etc/imladris')
    try:
        bot = parse_config((directory / 'bot.env').read_bytes(), 'bot')
        editor = parse_config((directory / 'editor.env').read_bytes(), 'editor')
        validate(bot, editor)
    except (ValueError, OSError) as error:
        print(f'Ошибка: {error}', file=sys.stderr)
        return 1
    print('Конфигурация заполнена; значения секретов не выводятся.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
