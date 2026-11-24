#!/usr/bin/env bash
# Activate both installed services only after server configuration and smoke checks.
set -euo pipefail
umask 0027
app_dir=/opt/vk_jewelry_bot

fail() { printf 'Ошибка: %s\n' "$*" >&2; exit 1; }
[[ "${EUID}" -eq 0 ]] || fail 'Запустите активацию на VPS под root.'
[[ -x "$app_dir/.venv/bin/python" ]] || fail 'Сначала выполните deploy/install.sh.'
[[ ! -e "$app_dir/.env" ]] || fail 'Перенесите конфигурацию из .env в /etc/imladris перед активацией.'

for unit in imladris-bot.service imladris-editor.service; do
    [[ -f "/etc/systemd/system/$unit" ]] || fail "Не установлена служба $unit."
done
for config in /etc/imladris/bot.env /etc/imladris/editor.env; do
    [[ -f "$config" && ! -L "$config" ]] || fail "Не найден обычный файл $config."
    [[ "$(stat -c '%u:%g:%a' "$config")" = 0:0:600 ]] ||
        fail "Установите для $config владельца root:root и права 0600."
done

# Validate the literal EnvironmentFile format without printing secrets.
"$app_dir/.venv/bin/python" "$app_dir/deploy/check_config.py"

# Old unit names may otherwise leave a second Long Poll process on the VPS.
for old_unit in vk-jewelry-bot.service jewelry-editor.service; do
    if systemctl is-active --quiet "$old_unit" || systemctl is-enabled --quiet "$old_unit" 2>/dev/null; then
        fail "Сначала остановите старую службу $old_unit и отключите её автозапуск."
    fi
done

systemctl daemon-reload
systemctl enable --now imladris-editor.service imladris-bot.service
for unit in imladris-editor.service imladris-bot.service; do
    systemctl is-enabled --quiet "$unit" || fail "Не включён автозапуск $unit."
    systemctl is-active --quiet "$unit" || fail "Не запущена служба $unit. Проверьте журнал systemd."
done
printf '%s\n' \
    'Обе службы запущены и включены в автозапуск после каждой загрузки VPS.' \
    'Теперь проверьте вход в админку, примерку через ВК и работу после реальной перезагрузки VPS.' \
    'Локальные копии бота с тем же токеном должны оставаться выключенными.'
