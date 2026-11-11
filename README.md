# Новогодний сборник «Маришкины рецепты»

Django 5.2, PostgreSQL, Robokassa, закрытый PDF. Покупка без аккаунта и без почты:
лендинг → Робокасса → подтверждение сервером → страница с кнопкой «Скачать сборник».
SMTP, Unisender, Gmail API, отправка писем и почтовый worker удалены.
Контактный адрес поддержки CONTACT_EMAIL остаётся обычной ссылкой для обращений.

## Структура

- core — лендинг, юридические страницы, настройки продавца.
- products — товар, цена, обложка, содержание, Admin.
- orders — заказы, согласие, защита от повторных запросов, страница скачивания.
- payments — Robokassa и проверяемый ResultURL.
- delivery — подписанные ссылки, приватный PDF, лимиты доступа; никаких писем.
- templates, static — русская адаптивная страница и стили.
- deploy, docs — Nginx, эксплуатация и настройка оплаты.

## Первый запуск

Python 3.12+; PowerShell на Windows:

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
$env:DEBUG = 'True'
.venv/Scripts/python.exe manage.py migrate
.venv/Scripts/python.exe manage.py seed_demo
.venv/Scripts/python.exe manage.py createsuperuser
.venv/Scripts/python.exe manage.py runserver 127.0.0.1:8002
```

Откройте http://127.0.0.1:8002/. SQLite допускается только для разработки.
seed_demo — только первый запуск, не выполняйте поверх настоящего товара.

Docker / PostgreSQL:

```bash
cp .env.example .env
chmod 600 .env
# Заполните SECRET_KEY, DB_PASSWORD, домен и остальные параметры.
docker compose up -d --build
docker compose exec web python manage.py createsuperuser
```

PostgreSQL доступен только внутри Docker; web — 127.0.0.1:8000.
init применяет миграции и collectstatic; успешное завершение init (Exited 0) нормально.
Настройки Nginx находятся в deploy/nginx.conf. Для production нужны HTTPS, домен,
правильные ALLOWED_HOSTS, CSRF_TRUSTED_ORIGINS, SITE_URL и TRUST_PROXY=True за этим proxy.
Не публикуйте порт приложения напрямую.

## Обновление сервера с прежней почтовой версии

В Termius, в /opt/marina-recipes. Сначала остановите web и старую рассылку, сделайте backup:

```bash
cd /opt/marina-recipes
docker compose stop web delivery
mkdir -p /srv/backups/cookbook
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > /srv/backups/cookbook/before-direct-download.dump
git pull --ff-only origin main
docker compose up -d --build --remove-orphans
docker compose ps -a
docker compose exec web python manage.py check
```

Миграция orders/0003 удаляет email покупателей и прежние статусы отправки.
Суммы, подтверждения оплаты, номера счетов, UUID, версии и сроки ссылок сохраняются.
Старый delivery-контейнер удаляется через --remove-orphans. Не используйте down -v:
там постоянные база и PDF. Значения SMTP/API в старом .env больше не используются;
их можно удалить. Даже при оставшемся EMAIL_BACKEND отправка принудительно отключена.

## Настройки

.env.example содержит только примеры. Основные переменные:

| Назначение | Переменные |
| --- | --- |
| Сайт | DEBUG, SECRET_KEY, ALLOWED_HOSTS, CSRF_TRUSTED_ORIGINS, SITE_URL, TRUST_PROXY |
| База | DB_NAME, DB_USER, DB_PASSWORD; Compose задаёт DATABASE_URL |
| Продавец | MERCHANT_NAME, MERCHANT_DETAILS, MERCHANT_COUNTRY, CONTACT_EMAIL, SELLER_DISPLAY_NAME, SELLER_INN, SELLER_OGRN |
| Продажи | SALES_ENABLED, LEGAL_READY, FISCALIZATION_READY, LEGAL_VERSION |
| Оплата | ROBOKASSA_MERCHANT_LOGIN, ROBOKASSA_PASSWORD1/2, ROBOKASSA_TEST_PASSWORD1/2, ROBOKASSA_TEST_MODE, ROBOKASSA_HASH_ALGORITHM |
| PDF | PRIVATE_ROOT, DOWNLOAD_DAYS (30), DOWNLOAD_LIMIT (20) |

Цена и файл берутся из Product в Admin; клиент не может подменить сумму или статус.
Боевые продажи требуют заполненных юридических документов, реквизитов, настоящего
товара, настройки кассового чека и платёжных паролей. Почтовых требований больше нет.
Электронный чек и необходимые контакты для него настраиваются у платёжного провайдера,
независимо от скачивания книги на сайте. Не объявляйте FISCALIZATION_READY без проверки.

## Робокасса и скачивание

В кабинете магазина укажите UTF-8 и алгоритм хэша, совпадающий с настройками сайта:

- ResultURL: https://marishkinirecepti.ru/payments/robokassa/result/ — POST.
- SuccessURL: https://marishkinirecepti.ru/payments/robokassa/success/ — GET (POST также поддерживается).
- FailURL: https://marishkinirecepti.ru/payments/robokassa/fail/ — GET.

ResultURL проверяет подпись паролем №2, сумму, валюту, InvId и Shp_* и только затем
сохраняет paid. Повторное событие не дублирует оплату. SuccessURL проверяет подпись
паролем №1, восстанавливает сессию только своего заказа и перенаправляет на /order/UUID/.
Один браузерный возврат никогда не подтверждает платёж. Если ResultURL запаздывает,
страница опрашивает статус каждые 3 секунды до 5 минут; потом остаётся ручная проверка.
FailURL возвращает к /#purchase с возможностью оплаты ещё раз; поздний FailURL для
уже оплаченного заказа владельца возвращает к скачиванию. Никакого автоматического списания.

Страница заказа доступна браузеру покупки или после подписанного возврата провайдера.
Чужой UUID недостаточен. Сохраните страницу в закладки, а PDF — на устройство.
После очистки cookie или смены браузера покупатель обращается в поддержку с номером
заказа и подтверждением платежа. Администратор сверяет платёж и в Admin выбирает
«Показать ссылки оплаченных заказов». Действие «Обновить доступ» отзывает старую ссылку.
Защищённая download-ссылка сама даёт доступ: передавайте только проверенному покупателю.

Срок 30 дней начинается при первом открытии оплаченной страницы; лимит — 20 скачиваний.
Обновление страницы не продлевает срок. HEAD не расходует лимит. Refunded закрывает
доступ. Приватный файл не публикуется через static/media. Если PDF отсутствует,
кнопка скачивания не появляется, ошибка записывается в журнал, оплата сохраняется.

## Подключение готового PDF

Файл marina-cookbook-approved.pdf (107 страниц, 91 рецепт) не входит в Git и Docker-образ.
Загрузите его через SFTP в /opt/marina-recipes/, затем:

```bash
docker compose cp marina-cookbook-approved.pdf web:/app/private/marina-cookbook-approved.pdf
docker compose exec -u root web chown 10001:10001 /app/private/marina-cookbook-approved.pdf
docker compose exec -u root web chmod 640 /app/private/marina-cookbook-approved.pdf
docker compose exec web python manage.py connect_cookbook
```

connect_cookbook сверяет SHA-256 с манифестом релиза и привязывает файл к товару,
не включая продажи и не меняя цену. При обновлении самого PDF обновите и манифест.

## Проверки

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test tests --settings=config.test_settings
# Только в отдельной тестовой PostgreSQL, роль должна иметь CREATEDB:
python manage.py test tests --settings=config.postgres_settings
```

Тесты не требуют платёжных ключей и не отправляют письма. Покрываются форма без email,
CSRF, серверная цена, подписи, повторные события, ожидание callback, signed GET/POST
возврат без cookie, запрет чужого/неоплаченного доступа, скачивание, отзыв и истечение,
отсутствующий PDF и миграция старых оплат. Конкурентные тесты требуют PostgreSQL.
Моки не доказывают боевую оплату: отдельно выполните внешний тест Robokassa, реальный
возврат на сайт и сохранение PDF на телефоне. Проверяйте кассовый чек отдельно.

## Эксплуатация

check_launch проверяет наличие production-настроек, не юридическую корректность
документов и не фактическое зачисление. Сверяйте длительные pending с кабинетом.
Автоматическая сверка потерянных callback и API возвратов не реализованы.
Сохраняйте зашифрованные резервные копии базы, private_files, public_images и .env вне
VPS, проверяйте восстановление. Не выводите полный docker compose config: он содержит
секреты. Фотографии и документы владельца не заменяются выдуманными материалами.
