# Ларец — каталог украшений

Веб-интерфейс для управления каталогом украшений: загрузка фото (уже без фона), названия
и категории, автоматическое добавление в витрину, удаление товаров. Работает как обычное
Node.js-приложение на вашем сервере.

В репозитории приложение находится в `tools/larets-server/`. Это самостоятельный
веб-каталог: его `data/items.json` и загруженные фотографии не синхронизируются с
каталогом VK-бота. Для добавления украшений и настройки примерки в боте используйте
[редактор украшений](../../vk_jewelry_bot/jewelry_editor/README.md).

Для локального запуска из корня репозитория:

```bash
cd tools/larets-server
npm install
npm start
```

Данные хранятся прямо на диске сервера:

- `data/items.json` — список товаров (название, категория, файл фото, дата добавления)
- `data/uploads/` — сами файлы фото

**Доступ к добавлению и удалению не защищён паролем** — управлять каталогом может
любой, кто откроет адрес сервера. Если сервер не изолирован (нет файрвола/VPN), учитывайте
это при выборе, кому давать ссылку.

## Требования

- VPS (или любой сервер) с постоянным диском и SSH-доступом
- Node.js версии 18 или новее (`node -v` чтобы проверить)

Если Node.js ещё не установлен на сервере (Ubuntu/Debian):

```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs
```

## Установка и запуск

1. Скопируйте папку проекта на сервер, например через `scp` (выполнить со своего компьютера):

```bash
scp -r ./tools/larets-server user@ваш-сервер:/opt/larets-server
```

   Команда выполняется из корня репозитория. Ниже используются прежние пути
   установки `/opt/larets-server`; перенос исходников в `tools/` их не меняет.
   При клонировании всего репозитория на сервер укажите фактический путь к
   `tools/larets-server` в `WorkingDirectory` и командах запуска.

2. Зайдите на сервер по SSH и установите зависимости:

```bash
ssh user@ваш-сервер
cd /opt/larets-server
npm install
```

3. Запустите сервер:

```bash
npm start
```

Приложение поднимется на порту `3000`. Проверить с самого сервера:

```bash
curl http://localhost:3000
```

Чтобы открыть его в браузере с вашего компьютера, зайдите на `http://IP-сервера:3000`
(порт нужно открыть в файрволе, см. ниже) — либо настройте домен и nginx (тоже ниже).

## Чтобы сервер продолжал работать после закрытия терминала и перезагрузки

Проще всего через [pm2](https://pm2.keymetrics.io/):

```bash
sudo npm install -g pm2
cd /opt/larets-server
pm2 start server.js --name larets
pm2 save
pm2 startup   # выполнит команду, которую нужно скопировать и запустить один раз
```

Полезные команды: `pm2 logs larets`, `pm2 restart larets`, `pm2 status`.

Альтернатива — systemd-юнит `/etc/systemd/system/larets.service`:

```ini
[Unit]
Description=Larets jewelry catalog
After=network.target

[Service]
WorkingDirectory=/opt/larets-server
ExecStart=/usr/bin/node server.js
Restart=always
Environment=PORT=3000
User=www-data

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now larets
sudo systemctl status larets
```

## Открыть доступ извне

**Вариант А — просто открыть порт** (быстро, без домена и HTTPS):

```bash
sudo ufw allow 3000/tcp
```

Каталог станет доступен по `http://IP-сервера:3000`.

**Вариант Б — домен + nginx + HTTPS** (рекомендуется для постоянного использования):

```nginx
server {
    listen 80;
    server_name ваш-домен.ru;

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        client_max_body_size 20M;
    }
}
```

Затем HTTPS через certbot:

```bash
sudo apt-get install -y certbot python3-certbot-nginx
sudo certbot --nginx -d ваш-домен.ru
```

## Резервное копирование

Все данные — это папка `data/`. Периодически копируйте её (например, `rsync` на другой диск
или в облако), чтобы не потерять фото и список товаров.

## Смена порта

По умолчанию сервер слушает порт 3000. Чтобы изменить:

```bash
PORT=8080 npm start
```

(в pm2/systemd — задать переменную окружения `PORT` соответствующим образом).
