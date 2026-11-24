#!/usr/bin/env bash
# Run only on the VPS after unpacking the runtime into /opt/vk_jewelry_bot.
# Installs dependencies and service definitions; never starts a VK poller.
set -euo pipefail
umask 0027

app_dir=/opt/vk_jewelry_bot
service_user=jewelry
service_group=jewelry
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"

fail() { printf 'Ошибка: %s\n' "$*" >&2; exit 1; }

[[ "${EUID}" -eq 0 ]] || fail 'Запустите установщик на VPS под root.'
[[ -r /etc/os-release ]] || fail 'Не удалось определить ОС сервера.'
# shellcheck disable=SC1091
source /etc/os-release
[[ "${ID:-}" = debian && "${VERSION_ID:-}" = 12 ]] ||
    fail 'Этот установщик рассчитан на Debian 12. Для другой ОС подготовьте отдельную установку.'
[[ "$script_dir" = "$app_dir/deploy" ]] ||
    fail 'Сначала распакуйте приложение в /opt/vk_jewelry_bot, затем запустите его deploy/install.sh.'
[[ ! -L "$app_dir" ]] || fail 'Папка приложения не должна быть символической ссылкой.'
for required in run.py requirements.txt requirements.lock.txt jewelry_editor/app.py jewelry_editor/requirements.txt bot/jewelry/gallery/manifest.json; do
    [[ -f "$app_dir/$required" ]] || fail "В комплекте отсутствует $required."
done
[[ ! -e "$app_dir/.env" ]] ||
    fail 'В папку приложения попал .env. Храните серверные секреты в /etc/imladris; .env не должен входить в комплект.'
for unit in imladris-bot.service imladris-editor.service; do
    if systemctl is-active --quiet "$unit"; then
        fail "Для обновления сначала остановите $unit; установщик не меняет зависимости работающего процесса."
    fi
done

if getent passwd "$service_user" >/dev/null; then
    current_home="$(getent passwd "$service_user" | cut -d: -f6)"
    current_shell="$(getent passwd "$service_user" | cut -d: -f7)"
    [[ "$current_home" = /var/lib/imladris && "$current_shell" = /usr/sbin/nologin ]] ||
        fail 'Пользователь jewelry уже существует с другими параметрами. Сначала проверьте его назначение вручную.'
fi

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    ca-certificates python3.11 python3.11-venv \
    libgles2 libseccomp2 libgl1 libportaudio2 libglib2.0-0 libgomp1

if ! getent group "$service_group" >/dev/null; then
    groupadd --system "$service_group"
fi
if ! getent passwd "$service_user" >/dev/null; then
    useradd --system --gid "$service_group" --create-home \
        --home-dir /var/lib/imladris --shell /usr/sbin/nologin "$service_user"
fi
[[ "$(id -gn "$service_user")" = "$service_group" ]] ||
    fail 'Основная группа пользователя jewelry должна называться jewelry.'

if [[ -e "$app_dir/.venv" && ! -x "$app_dir/.venv/bin/python" ]]; then
    fail 'Найдено повреждённое окружение .venv; проверьте его перед повторной установкой.'
fi
if [[ ! -e "$app_dir/.venv" ]]; then
    python3.11 -m venv "$app_dir/.venv"
fi
"$app_dir/.venv/bin/python" -c 'import sys; assert sys.version_info[:2] == (3, 11), "Нужен Python 3.11"'
"$app_dir/.venv/bin/python" -m pip install --disable-pip-version-check \
    -r "$app_dir/requirements.txt" -r "$app_dir/jewelry_editor/requirements.txt"
"$app_dir/.venv/bin/python" -m pip check

# Content is preserved. Only runtime data and the shared catalogue are writable
# by the service account; code and virtualenv stay owned by root.
chown -R root:"$service_group" "$app_dir"
chmod -R u=rwX,g=rX,o= "$app_dir"
install -d -m 0750 -o "$service_user" -g "$service_group" \
    "$app_dir/data" "$app_dir/data/tmp" "$app_dir/data/cache" \
    "$app_dir/data/cache/matplotlib"
chown -R "$service_user:$service_group" "$app_dir/data" "$app_dir/bot/jewelry/gallery"
chmod -R u=rwX,g=rX,o= "$app_dir/data" "$app_dir/bot/jewelry/gallery"
install -d -m 0700 -o root -g root /etc/imladris

# Existing environment files are never created, replaced or printed here.
for unit in imladris-bot.service imladris-editor.service; do
    target="/etc/systemd/system/$unit"
    [[ ! -L "$target" ]] || fail "Служба $unit установлена символической ссылкой; проверьте её перед заменой."
    if [[ -f "$target" ]] && ! cmp -s -- "$script_dir/$unit" "$target"; then
        backup="$(mktemp "$target.before-install.XXXXXXXX")"
        cp -p -- "$target" "$backup"
    fi
    install -m 0644 -o root -g root "$script_dir/$unit" "$target"
done
systemctl daemon-reload

printf '%s\n' \
    'Файлы приложения и службы установлены. Бот и редактор НЕ запущены.' \
    'Подготовьте /etc/imladris/bot.env и /etc/imladris/editor.env с правами root:root 0600.' \
    'Шаблоны: /opt/vk_jewelry_bot/deploy/bot.env.example и editor.env.example.' \
    'До запуска остановите другие копии бота с тем же токеном, включая локальный тест.' \
    'После проверки конфигурации и нативной примерки запустите:' \
    '  bash /opt/vk_jewelry_bot/deploy/activate.sh' \
    'Для проверки состояния:' \
    '  systemctl status imladris-editor.service imladris-bot.service --no-pager'
