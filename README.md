# Новогодний сборник «Маришкины рецепты»

Django 5.2 LTS, PostgreSQL, ЮKassa, приватный PDF.
Лендинг → оплата на странице ЮKassa → проверка сервером → «Скачать сборник».
Без аккаунта и без рассылки. Контакт поддержки: valeron684@mail.ru.

Если в браузере уже сохранён оплаченный заказ на текущий сборник, кнопки покупки
ведут на страницу скачивания, а повторный POST оплаты возвращает к этому заказу
без создания нового платежа. При другом браузере или удалённых cookie нужно
восстановить доступ через поддержку. Ожидающие оплаты и возвращённые заказы
не считаются оплаченной покупкой; окончательные проверки доступа остаются на сервере.

## Обновить существующий сервер

В Termius:

```bash
cd /opt/marina-recipes
git pull --ff-only origin main
python3 deploy/configure_yookassa.py --shop-id 1527129
```

На скрытый запрос вставить **тестовый ключ ЮKassa**. Затем:

```bash
docker compose stop web
mkdir -p /srv/backups/cookbook
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > /srv/backups/cookbook/before-yookassa.dump
docker compose up -d --build --remove-orphans
docker compose exec web python manage.py check
```

Не используйте `down -v`: в volumes база и сборник. Init автоматически применяет
миграции и собирает static. Старые оплаченные заказы сохраняют доступ. Неоплаченные
заказы прежнего провайдера не конвертируются в оплаченные; оформите новый через главную.

В кабинете **тестового магазина** ЮKassa укажите HTTP-уведомления:
`https://www.marishkinirecepti.ru/payments/yookassa/webhook/`.
События: `payment.succeeded`, `payment.canceled`, `refund.succeeded`.
Возврат на сайт передаётся в API автоматически; отдельные SuccessURL/FailURL не нужны.
Даже без webhook при возврате сайт проверяет статус напрямую через API.

## Первый локальный запуск

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.venv/Scripts/python.exe manage.py migrate
.venv/Scripts/python.exe manage.py seed_demo
.venv/Scripts/python.exe manage.py runserver 127.0.0.1:8002
```

http://127.0.0.1:8002/. SQLite только для разработки. seed_demo — только для новой БД,
не запускать поверх настоящего товара. Для production заполнить .env и использовать
`docker compose up -d --build`, PostgreSQL, HTTPS и deploy/nginx.conf.

## Структура

- core — лендинг, юридические страницы, продавец и диагностика.
- products — товар, цена и имя приватного PDF, Admin.
- orders — согласие, заказы, защита от повторных покупок, страница скачивания.
- payments — REST API ЮKassa, webhook, проверка платежей/возвратов.
- delivery — подписанные ссылки на файл с ограничением срока/числа скачиваний.
- templates / static — адаптивный русский интерфейс.
- deploy / docs — настройка, обновление и эксплуатация.

## Переменные окружения

Секреты только в .env (игнорируется git). Пример — .env.example.

| Назначение | Переменные |
| --- | --- |
| Сайт | DEBUG, SECRET_KEY, ALLOWED_HOSTS, CSRF_TRUSTED_ORIGINS, SITE_URL, TRUST_PROXY |
| База | DB_NAME, DB_USER, DB_PASSWORD; Compose задаёт DATABASE_URL |
| Оплата | SALES_ENABLED, YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY, YOOKASSA_TEST_MODE |
| PDF | PRIVATE_ROOT, DOWNLOAD_DAYS, DOWNLOAD_LIMIT |
| Владелец | CONTACT_EMAIL, SELLER_DISPLAY_NAME, SELLER_INN, SELLER_OGRN, MERCHANT_NAME, MERCHANT_DETAILS, MERCHANT_COUNTRY |
| Проверка запуска | LEGAL_READY, FISCALIZATION_READY, LEGAL_VERSION |

В тестовом режиме требуется ключ test_. Боевой ключ не используется как запасной.
Инструкция по протоколу, проверкам и фискализации: [docs/payment.md](docs/payment.md).
Исходящий email полностью отключён; SMTP и почтовые API не нужны.

## Настоящий PDF

Готовый файл не лежит в Git и не входит в образ. Загрузить через SFTP в приватный
каталог, скопировать в volume (`docker compose cp ... web:/app/private/ИМЯ.pdf`),
назначить владельца 10001:10001, права 640. В Product.pdf_name указать только имя файла.
Нельзя размещать PDF в static или public-media.
Для уже подготовленного утверждённого файла есть команда `connect_cookbook`:
её параметры и контрольную сумму смотрите через `manage.py connect_cookbook --help`.

## Проверки

```powershell
.venv/Scripts/python.exe manage.py check
.venv/Scripts/python.exe manage.py makemigrations --check --dry-run
.venv/Scripts/python.exe manage.py test tests --settings=config.test_settings
```

PostgreSQL: задать DATABASE_URL и запустить `manage.py test tests --settings=config.postgres_settings`.
CI использует PostgreSQL 17 и Python 3.12. Внешний API в автоматических тестах замокан;
отдельная проверка реальным тестовым ключом описана в docs/QA.md.

Перед реальными продажами: `manage.py check --deploy` и `manage.py check_launch`,
внешняя тестовая оплата, настройка чеков у провайдера, резервное копирование и проверка
восстановления. Владелец предоставляет окончательный PDF, реквизиты и юридические документы.
