# Тепло дома — магазин электронного сборника

Русскоязычный Django-монолит: лендинг → email → платёжная ссылка Robokassa → подписанное уведомление → очередь в PostgreSQL → письмо → закрытый PDF. Аккаунт покупателю не нужен.

**Реальные продажи по умолчанию выключены.** В репозитории нет настоящей книги, реквизитов продавца, платёжных ключей или SMTP-учётной записи. Демо-PDF — одностраничная техническая заглушка с надписью DEMO. Нельзя выдавать его за сборник из 36 рецептов.

## Состав

```text
config/       настройки, URL, WSGI, отдельные настройки тестов
core/         лендинг, юридические страницы, SEO, защитные заголовки
products/     продукт, преимущества, главы, рецепты, превью и Admin
orders/       заказы, проверка формы, снимок цены, идемпотентность, лимиты
payments/     Robokassa, проверенный ResultURL, журнал событий без карточных данных
delivery/     письма, подписанные ссылки, DB worker, повторная отправка
templates/    Django HTML и текстовая/HTML-версии письма
static/       CSS, небольшой JS, локальные WebP и favicon
tests/        функциональные тесты и проверки конкуренции PostgreSQL
deploy/       пример Nginx и безопасного проксирования
docs/         протокол оплаты, эксплуатация, источники изображений, QA
```

Python 3.12+, Django 5.2 LTS, PostgreSQL, Gunicorn, WhiteNoise. SQLite поддержан только для быстрой локальной демонстрации. Node.js не нужен. В production настройки отклоняют SQLite, слабый ключ и dev-платежи.

## Первый запуск через Docker Compose

Нужны Docker Engine/Desktop и Compose v2. Все команды выполнять **из каталога с manage.py**.

```bash
cp .env.example .env
```

В PowerShell вместо `cp` можно использовать `Copy-Item .env.example .env`. Заполните `DB_PASSWORD` случайной строкой (например, 32 случайных байта в hex); это значение попадёт в URL, поэтому используйте hex либо URL-кодирование. Не помещайте секреты в Git или вывод команд.

```bash
docker compose up --build -d
docker compose exec web python manage.py seed_demo --with-pdf
docker compose exec web python manage.py apply_holiday_theme
docker compose exec web python manage.py createsuperuser
```

Откройте http://127.0.0.1:8000, Admin — http://127.0.0.1:8000/admin/ . `init` выполняет миграции и collectstatic до запуска web и delivery. PostgreSQL не публикует порт; web привязан только к 127.0.0.1. Данные БД, закрытые PDF, публичные изображения и static живут в отдельных persistent volumes. `seed_demo` ничего не перезаписывает и откажется работать, если продукт уже существует.

Новогодняя презентация описана в [docs/holiday-redesign.md](docs/holiday-redesign.md). Команда `apply_holiday_theme` обновляет только активный демопродукт, предварительно сохраняет JSON-копию в `work/` и сохраняет цену, путь PDF, загрузки и подтверждённые рецепты. Для реального товара редактируйте содержание через существующий Admin. Локально без Docker: `python manage.py apply_holiday_theme` после `seed_demo`.

Для локального просмотра платёжные пароли не нужны. Без них оформление оплаты закрыто. Для внешнего теста используйте только собственный тестовый магазин Robokassa: задайте ROBOKASSA_MERCHANT_LOGIN, ROBOKASSA_TEST_PASSWORD1/2, ROBOKASSA_TEST_MODE=True и SALES_ENABLED=True. В DEBUG=True этот режим допускает демопродукт и консольную почту. Он отправляет покупателя в настоящий тестовый интерфейс с IsTest=1; локальная кнопка имитации оплаты удалена.

## Запуск без Docker

```bash
python -m venv .venv
# Linux/macOS:
. .venv/bin/activate
# Windows PowerShell: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
python manage.py seed_demo --with-pdf
python manage.py createsuperuser
python manage.py runserver 127.0.0.1:8000
```

Не задавайте `DATABASE_URL` для быстрого SQLite-превью. Для PostgreSQL задайте `postgres://USER:URL_ENCODED_PASSWORD@127.0.0.1:5432/DB` и повторите миграции. Системный Python должен быть версии 3.12 или новее.

Для реальных webhook в отдельном терминале держите `python manage.py deliver_pending --loop` либо запускайте `python manage.py deliver_pending` раз в минуту через systemd timer/cron. Compose уже запускает процесс `delivery`.

## Тестирование

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test tests --settings=config.test_settings
```

Быстрый набор использует временную SQLite, временные PDF, locmem email и mocked HTTP. Три конкурентных теста на SQLite пропускаются, потому что она не поддерживает блокировки PostgreSQL.

Проверка на PostgreSQL (роль тестовой БД должна иметь CREATEDB):

```bash
# Задайте DATABASE_URL только для отдельной dev/test БД.
python manage.py test tests --settings=config.postgres_settings
# В Compose URL уже передан:
docker compose exec web python manage.py test tests --settings=config.postgres_settings
```

Тесты не используют настоящие платёжные ключи и не отправляют настоящие письма. Набор покрывает цену на сервере, CSRF, подписи Robokassa, валюту/сумму/заказ/режим счёта, повторные callback, безопасные SuccessURL/FailURL и сохранность исторических заказов, доставку/повтор/отзыв ссылки, лимиты и закрытый Admin. Отдельные потоки проверяют, что два worker не отправляют два письма и два одинаковых события дают одну запись.

## Настройки

Полный перечень с комментариями — `.env.example`.

| Группа | Переменные |
|---|---|
| Домен и безопасность | `DEBUG`, `SECRET_KEY`, `SITE_URL`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `TRUST_PROXY` |
| БД | `DATABASE_URL`; в Compose — `DB_NAME`, `DB_USER`, `DB_PASSWORD` |
| Продавец | `MERCHANT_COUNTRY`, `MERCHANT_NAME`, `MERCHANT_DETAILS`, `CONTACT_EMAIL` |
| Разрешение продаж | `SALES_ENABLED`, `LEGAL_READY`, `FISCALIZATION_READY`, `LEGAL_VERSION` |
| Robokassa | `ROBOKASSA_MERCHANT_LOGIN`, `ROBOKASSA_PASSWORD1/2`, `ROBOKASSA_TEST_PASSWORD1/2`, `ROBOKASSA_TEST_MODE`, `ROBOKASSA_HASH_ALGORITHM`, `ROBOKASSA_CURRENCY`, `ROBOKASSA_PAYMENT_METHOD` |
| Доставка | `PRIVATE_ROOT`, `DOWNLOAD_DAYS` (30), `DOWNLOAD_LIMIT` (20) |
| Почта | `EMAIL_BACKEND`, `DEFAULT_FROM_EMAIL`, `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, `EMAIL_USE_SSL` |

Название, описание, цена, количество рецептов/страниц, обложка, главы, преимущества, рецепты, изображения, реальное наличие рецепта в PDF, имя закрытого файла и юридические тексты редактируются в Admin. Нет необходимости изменять шаблоны для этих данных. Цена/название/валюта фиксируются в заказе при его создании.

## Подключение Robokassa

Новые покупки используют только **Robokassa** и документированный прямой интерфейс `https://auth.robokassa.ru/Merchant/Index.aspx`. Сервер создаёт подписанную ссылку со стабильным числовым InvId; отдельный удалённый Invoice API и выдуманный Currency-параметр не используются. Алгоритм по умолчанию SHA256 должен совпадать с кабинетом. Это digest строки по документации, не HMAC. Подробные формулы, сверка сумм и ограничения — [docs/payment.md](docs/payment.md).

```dotenv
ROBOKASSA_MERCHANT_LOGIN=YOUR_MERCHANT_LOGIN
ROBOKASSA_TEST_PASSWORD1=YOUR_TEST_PASSWORD1
ROBOKASSA_TEST_PASSWORD2=YOUR_TEST_PASSWORD2
ROBOKASSA_TEST_MODE=True
ROBOKASSA_HASH_ALGORITHM=SHA256
ROBOKASSA_CURRENCY=RUB
SALES_ENABLED=True
```

Нужны ваши тестовые пароли из технических настроек Robokassa. Рабочие пароли хранятся отдельно в ROBOKASSA_PASSWORD1/2 и никогда не используются как fallback в тестовом режиме. Без заполненных паролей оплаты не открываются. ROBOKASSA_PAYMENT_METHOD — необязательный alias IncCurrLabel, пустое значение оставляет выбор провайдеру.

В кабинете магазина задайте UTF-8, SHA256 и реальные HTTPS URL:

| Настройка | URL | Метод |
|---|---|---|
| ResultURL | https://YOUR_DOMAIN/payments/robokassa/result/ | POST |
| SuccessURL | https://YOUR_DOMAIN/payments/robokassa/success/ | GET |
| FailURL | https://YOUR_DOMAIN/payments/robokassa/fail/ | GET |

ResultURL сверяет подпись паролем №2, OutSum, InvId и подписанные Shp_currency/Shp_mode/Shp_order, сохраняет paid и отвечает строго OK{InvId}. Боевые суммы с шестью знаками сравниваются без округления. Повтор не создаёт второй платёж/письмо. Callback продолжает завершать существующие покупки при SALES_ENABLED=False. SuccessURL с паролем №1 только показывает статус; FailURL не меняет состояние заказа. Смена глобального тестового режима не меняет снимок режима ранее созданного счёта.

Для production задайте DEBUG=False, ROBOKASSA_TEST_MODE=False, настоящие PASSWORD1/2, SMTP, PostgreSQL, HTTPS и реквизиты. Подготовьте реальные PDF/превью/состав, снимите Product.is_demo и LegalPage.is_draft, подтвердите LEGAL_READY/FISCALIZATION_READY. Выполните `check --deploy`, `check_launch` и внешнюю приёмку. FISCALIZATION_READY — подтверждение настройки владельцем, не подключение кассы. Приложение отправляет подтверждение и ссылку, не кассовый чек; передачу налоговой номенклатуры и кассу нужно настроить отдельно, если они обязательны.

Профиль реализации — РФ/RUB. ROBOKASSA_CURRENCY сверяется с ценой и в текущем профиле допускает RUB; для другой страны/валюты нужна отдельная проверка договора и адаптация. [Официальный интерфейс](https://docs.robokassa.ru/ru/pay-interface), [уведомления](https://docs.robokassa.ru/ru/notifications-and-redirects), [тестовый режим](https://docs.robokassa.ru/ru/testing-mode).

### Миграция существующего магазина

Миграция только добавляет RobokassaInvoice. Старые UUID, email, суммы, provider, статусы, токены и доставки не переписываются; старые paid продолжают скачивание. Это проверяет отдельный migration-тест. Admin показывает InvId, режим и исторического провайдера. Новый Order всегда robokassa, фальшивый dev-провайдер и старые CP_* удалены.

Перед production-обновлением сделайте backup и завершите/сверьте pending счета прежнего провайдера; старый callback удалён. Если MerchantLogin уже использовался в другой системе, согласуйте отдельный магазин или установите PostgreSQL sequence RobokassaInvoice выше максимального InvId из кабинета **до** первых оплат. Не обнуляйте последовательность после восстановления. Сессия старого заказа получает новый checkout nonce без изменения исторической записи.

## SMTP и повторная доставка

Для SMTP:

```dotenv
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
DEFAULT_FROM_EMAIL=Название магазина <books@YOUR_DOMAIN>
EMAIL_HOST=YOUR_SMTP_HOST
EMAIL_PORT=587
EMAIL_HOST_USER=YOUR_SMTP_USER
EMAIL_HOST_PASSWORD=YOUR_SMTP_PASSWORD
EMAIL_USE_TLS=True
EMAIL_USE_SSL=False
```

Если провайдер требует implicit TLS/465, используйте порт 465, `EMAIL_USE_SSL=True`, `EMAIL_USE_TLS=False`. Настройте SPF/DKIM/DMARC у своего SMTP-провайдера. Timeout — 10 секунд. Статус `sent` означает принятие сообщения backend/SMTP, не подтверждённое попадание во входящие. HTML и обычный текст находятся в `templates/email/`.

После подтверждённого ResultURL оплаченный заказ сам является устойчивой задачей в БД. Worker проверяет очередь каждые 15 секунд, использует возрастающие интервалы, максимум 8 автоматических попыток. Ошибки `pdf_missing` и `email_failed` видны в Admin. Мониторьте worker и failed-заказы.

```bash
python manage.py deliver_pending
python manage.py resend_delivery ORDER_UUID
# Обновляет срок, отзывает старую ссылку и обнуляет счётчик:
python manage.py resend_delivery ORDER_UUID --renew
```

Те же действия есть в Admin. Отправка возможна только для подтверждённого `paid`. При отсутствующем PDF письмо не уходит, успех не записывается. Исторический refunded закрывает скачивание и не активируется callback. FailURL после подтверждения не отменяет оплату. Автоматические API возвратов Robokassa и синхронизация их статусов в эту замену не добавлены; оператор сверяет возвраты через кабинет.

Ссылка подписана Django secret key, содержит UUID заказа и случайную версию доступа. Срок считается от первой выдачи, по умолчанию 30 дней/20 попыток GET. HEAD не расходует лимит. Купленный файл можно хранить без ограничения; поддержка восстанавливает доступ проверенному покупателю. Лимит считает начало выдачи, а не доказанное полное скачивание. PDF не доступен через static/media, путь не принимается от покупателя.

Обычные дубликаты webhook/worker предотвращаются транзакциями и уникальными ограничениями. SMTP не даёт строгой гарантии «ровно один раз»: авария после принятия письма SMTP, но до commit БД может привести к повтору. Используется стабильный Message-ID, но не все SMTP-сервисы дедуплицируют его. Это ограничение описано честно; не обещайте математически невозможную гарантию на обычном SMTP.

## Linux VPS и эксплуатация

Подробно: `docs/operations.md`. Для небольшого магазина достаточно одного VPS, двух Gunicorn workers и одного delivery-процесса; запас зависит от диска/SMTP/трафика PDF. Нагрузочный тест инфраструктуры не выполнялся.

- Укажите DNS A/AAAA, получите HTTPS-сертификат и настройте Nginx по `deploy/nginx.conf`. Скопируйте `deploy/cookbook-proxy.conf` в `/etc/nginx/snippets/cookbook-proxy.conf`.
- Оставьте порт приложения только на loopback. Nginx должен **перезаписывать** forwarding headers. Только после этого задайте `TRUST_PROXY=True`. В `ALLOWED_HOSTS` сохраните `localhost` для health check и добавьте свой домен, в `CSRF_TRUSTED_ORIGINS` — его HTTPS origin.
- Пример: `DEBUG=False`, новый случайный `SECRET_KEY` длиной ≥50, `SITE_URL=https://YOUR_DOMAIN`, PostgreSQL, настоящие почтовые настройки. Не меняйте SECRET_KEY без плана отзыва ссылок/сессий.
- WhiteNoise отдаёт собранные static с хешами, сжатием и долгим кешем. Публичные изображения из Admin отдаёт Nginx; настройте bind mount/копирование **только public-media** в указанный alias. Закрытый volume к Nginx не подключать.
- Для Admin настройте VPN/IP allowlist по возможностям вашей инфраструктуры, сильный пароль и минимум staff-пользователей. В приложении есть лимит входа, в Nginx — дополнительный лимит. TLS/cookies/HSTS/CSP/CSRF включены production-настройками.
- Делайте шифрованные off-site backups БД, private PDF, public images и конфигурации; регулярно проверяйте восстановление. Не выполняйте `docker compose down -v` на рабочем магазине — это удалит volumes.

## Что владелец должен заменить

Реальный PDF и права на него; точный состав/объём/цену; обложку и реальные превью; проверить демонстрационные рецепты и их наличие в PDF; контакт и реквизиты; документы и применимые сроки возврата/хранения данных; договор эквайринга; кассу, если требуется; домен/HTTPS; SMTP.

Демо-изображения сгенерированы встроенным ImageGen, хранятся локально, происхождение и запросы записаны в `docs/assets.md`. Никаких вымышленных отзывов, скидок, рейтингов или гарантий нет. Юридические страницы являются редактируемыми шаблонами, не заключением о соответствии закону.

## Границы проверенного результата

Результаты фактической проверки — `docs/QA.md`. Мокированные тесты не доказывают работу боевого эквайринга. Без учётных записей не выполнялись реальные платежи/SMTP, фискализация, DNS/HTTPS-развёртывание и проверка inbox. Docker отсутствовал в среде сборки, поэтому Compose не запускался. Проект подготовлен к подключению инфраструктуры; принимать деньги до завершения этих пунктов нельзя.

## Совместимость iPhone Safari

Дизайн, фотографии и секции сохранены. Текстовые значки заменены собственными inline SVG с namespace/viewBox/currentColor/явными размерами и aria-hidden. Нет icon fonts, emoji, внешних спрайтов или CSS masks. В compat.css добавлены safe-area, 16 px email input без запрета масштабирования, fallback изображений без aspect-ratio, устранена зависимость от :has и flex gap, нормализован appearance. CSP разрешает платёжный редирект формы только на auth.robokassa.ru. CSS-target — iOS Safari 14+.

Размеры 320/375/390/430/768/desktop проверяются отдельно; Chromium viewport не доказывает Safari-совместимость. Реальные iPhone/iPad и macOS Safari, Firefox и Android требуют внешней приёмки. Отчёт — docs/QA.md.

## Новая витрина
Структура, отзывы и настройка Telegram: [docs/cozy-redesign.md](docs/cozy-redesign.md). После обновления выполните миграции.


## Оферта продавца

Страница `/legal/offer/` содержит текст из `oferta_910620715151.docx`, включая реквизиты и исходную нумерацию. Миграция `core.0002_import_owner_offer` устанавливает эту редакцию при `python manage.py migrate`; затем текст можно редактировать в Django Admin → Legal pages. Другие юридические страницы и настройки продавца не заменяются.

В оригинале не заполнены адреса сайта. Поэтому оферта пока имеет `is_draft=True`; после заполнения и проверки владелец может снять этот флаг в Admin. Импорт документа не включает продажи и не меняет настройки оплаты. Формулировки предоставленного документа сохранены без юридической переработки.
