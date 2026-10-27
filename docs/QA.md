# Проверка обновления Robokassa и iPhone CSS — 27.10.2026

## Выполнено

- Существующие приложения и редакционный дизайн сохранены. Новый провайдер — только Robokassa. Старый адаптер/endpoint/CP_* и локальная имитация оплаты удалены. Исторический provider в Order не переписывается.
- Миграция payments/0002_robokassainvoice.py применена к локальной SQLite и выделенной PostgreSQL 18.1. Добавлена отдельная числовая последовательность InvId. В пользовательской dev-БД сохранён существующий оплаченный тестовый заказ; реальных pending прежнего провайдера там нет.
- На PostgreSQL прошли **58 тестов, OK**, включая 3 многопоточных: параллельные checkout, одинаковые ResultURL и отправители. MigrationExecutor-тест проверил сохранность старого paid-заказа, email, суммы, provider IDs, времени оплаты и download token.
- Проверены SHA256/MD5 по настройке, сортировка Shp_*, оба набора паролей, суммы с 6 знаками, подпись в верхнем регистре, неверные сумма/валюта/UUID/режим/InvId, parameter pollution, дубли, безопасные SuccessURL/FailURL, отправка, сбой SMTP и retry, закрытый PDF, старые paid и защита refunded.
- manage.py check без ошибок; makemigrations --check --dry-run: изменений нет; collectstatic и node --check успешны. Production check --deploy имеет только прежнее осознанное предупреждение HSTS preload, без регистрации домена preload не включён.
- Браузерная проверка Chromium: **320, 375, 390, 430, 768, 1440 px**. На всех ширинах scrollWidth <= viewport, email input 16 px, в Django-странице 30 inline SVG. Исправлено найденное переполнение меню на 320 px и перенос символа рубля.
- Меню открывается, закрывается Escape; recipe/FAQ раскрываются клавишей Enter. У иконок времени проверены реальные 13×13 px и непрозрачный currentColor stroke. Фотографии и секции сохранены.
- Сохранены отдельные мобильный (390×844) и desktop (1440×900) скриншоты рядом с архивом в outputs.
- Публичная демоверсия обновлена отдельным статическим экспортом: HTTP 200 для страницы, compat.css и Apple PNG; /admin/ возвращает 404; checkout формы/CSRF/личные данные не экспортируются. Здесь 29 SVG, поскольку платёжная форма удалена. Ссылка временная и зависит от запущенного туннеля.

## Причины и исправления Safari-рисков

Иконки были Unicode-символами, зависели от выбранного системного шрифта и emoji fallback. Они заменены кодовыми inline SVG с xmlns, viewBox, width/height, currentColor, stroke/fill, aria-hidden и focusable=false. Нет внешнего спрайта, icon font, mask или подмены на emoji. Добавлен собственный Apple touch PNG.

Добавлены viewport-fit=cover, env(safe-area-inset-*), 16 px email field без user-scalable=no, -webkit-appearance для input/button и text-size-adjust. Устранена зависимость от :has и flex gap. Изображения имеют padding-ratio fallback без aspect-ratio; min-width:0 предотвращает распирание Grid. Добавлены focus fallback, предсказуемые SVG-размеры и reduced-motion. Sticky/fixed/backdrop-filter/mask на страницах не применяются. CSS-target — iOS Safari 14+.

CSP form-action явно разрешает только self и auth.robokassa.ru: браузеры по-разному проверяют внешние redirect после POST. Сама CSRF-проверка формы не ослаблена. Cross-site Success/Fail POST не зависит от session cookie Safari и не меняет платёжный статус.

## Не проверено и остаётся настроить

**Реальный Safari/iPhone/iPad и macOS Safari недоступны в Windows-среде.** Chromium viewport не доказывает совместимость WebKit. Также не выполнена отдельная приёмка Firefox, Edge, Chrome Android, физических safe-area и сохранения PDF на iOS. Не заявляется «безупречно работает на всех устройствах» или балл Lighthouse/WCAG.

Не предоставлены MerchantLogin и собственные тестовые/боевые пароли Robokassa: внешняя sandbox и боевая транзакции не выполнялись. Локальные тесты считают подписи и эмулируют уведомления; это не подтверждение внешнего эквайринга. После credentials нужно пройти тестовую оплату по официальной инструкции и проверку iPhone → Robokassa → возврат → письмо → download.

SMTP/inbox, SPF/DKIM/DMARC, DNS/HTTPS VPS, Docker/Gunicorn Linux и обязательная фискализация остаются инфраструктурной приёмкой. Приложение отправляет подтверждение, не фискальный чек; кассу/номенклатуру нужно подключить отдельно. Новые API возвратов и автоматическая сверка статусов Robokassa не реализованы: оператор сверяет кабинет и возвраты. Обычные дубли защищены; редкое повторное письмо после аварии между SMTP acceptance и DB commit возможно.

Перед production-миграцией обязательны backup, сверка/завершение pending прежнего провайдера и согласование диапазона InvId, если MerchantLogin уже использовался. См. README и docs/payment.md.
