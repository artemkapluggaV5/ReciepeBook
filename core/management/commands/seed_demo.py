from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from core.models import LegalPage
from products.models import Product, Benefit, Chapter, Recipe

LEGAL = {
    'privacy': ('Политика конфиденциальности', 'Оператор: [наименование, статус, ИНН, адрес, контакты]. Юрисдикция: [указать].\n\nЦели: оформление заказа, учёт оплаты, доставка PDF, ответы на обращения. Обрабатываются email, сведения о заказе, платеже и согласии, технические данные безопасности. Данные карты обрабатывает платёжный провайдер; сайт их не получает.\n\nУкажите правовые основания, сроки хранения каждой категории, порядок удаления, перечень обработчиков (хостинг, SMTP, эквайринг), место хранения, трансграничную передачу и способы реализации прав покупателя. Не используйте email для рекламы без отдельного согласия.'),
    'consent': ('Обработка персональных данных', 'Оператор: [полные реквизиты]. Контакт для обращений: [email].\n\nСогласие запрашивается для оформления и исполнения заказа: email, сведения об оплате и доставке. Укажите операции обработки, срок действия, порядок отзыва и основания хранения обязательных учётных данных после отзыва. Рассылки рекламы не предусмотрены.\n\nРазделите основания исполнения договора и отдельного согласия там, где этого требует применимое право. Проверьте требования к отдельной форме согласия и локализации данных.'),
    'offer': ('Публичная оферта', 'Продавец: [имя/организация, статус, ИНН, адрес, контакты]. Покупатель: лицо, принимающее условия при оформлении заказа. Юрисдикция: [указать].\n\nПредмет: предоставление персонального доступа к электронному сборнику в формате PDF. Название, состав, цена и валюта указаны на странице товара. Печатная книга не поставляется. Оплата разовая на странице платёжного провайдера.\n\nДоставка осуществляется после подтверждения платежа: письмо с персональной ссылкой. Укажите срок доставки, поддержку, лицензию на личное использование, технические требования, правила исправления неверного email, ответственность сторон и порядок разрешения споров.\n\nПроверьте точное соответствие описания содержимому PDF. Установите правила возврата с учётом обязательных прав потребителя; ссылка на раздел доставки и возврата.'),
    'refunds': ('Доставка и возврат', 'Товар — цифровой PDF, без физической доставки. После подтверждения оплаты ссылка направляется на email заказа. Срок и лимит ссылки указаны в письме; сохранённый файл остаётся у покупателя. Для восстановления доступа обратитесь в поддержку.\n\nЕсли письмо не пришло, проверьте «Спам» и свяжитесь с продавцом. При ошибке в файле, двойном списании, недоставке или несоответствии описанию сообщите номер заказа и email покупки. Не отправляйте номер карты.\n\nУкажите применимые основания, порядок, сроки рассмотрения и возврата средств. Не ограничивайте обязательные права потребителя общей формулировкой «цифровые товары возврату не подлежат». Этот шаблон не устанавливает безусловного запрета или обещания возврата.'),
    'contacts': ('Контакты продавца', '[Наименование или ФИО]\n[Статус продавца и ИНН]\n[Адрес, страна и применимая юрисдикция]\n[Контактный email и время ответа]\n\nДля решения вопросов по заказу укажите номер заказа и email покупки. Реквизиты карты не нужны.'),
}

def demo_pdf(path):
    # Intentionally a one-page technical PDF, never represented as the actual cookbook.
    text = b'BT /F1 22 Tf 60 740 Td (DEMO - NOT THE COOKBOOK) Tj 0 -40 Td /F1 12 Tf (Replace with the real licensed PDF before enabling sales.) Tj ET'
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>', b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
               b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
               b'<< /Length ' + str(len(text)).encode() + b' >>\nstream\n' + text + b'\nendstream']
    data, offsets = b'%PDF-1.4\n', [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data += f'{i} 0 obj\n'.encode() + obj + b'\nendobj\n'
    xref = len(data)
    data += f'xref\n0 {len(objects)+1}\n0000000000 65535 f \n'.encode()
    data += b''.join(f'{offset:010d} 00000 n \n'.encode() for offset in offsets[1:])
    data += f'trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode()
    path.write_bytes(data)

class Command(BaseCommand):
    help = 'Create clearly labelled demo content without overwriting existing content.'
    def add_arguments(self, parser):
        parser.add_argument('--with-pdf', action='store_true')
    @transaction.atomic
    def handle(self, *args, **options):
        if Product.objects.exists():
            raise CommandError('Products already exist; nothing overwritten.')
        product = Product.objects.create(description='Сборник для неспешных завтраков, уютных ужинов и маленьких поводов собраться за одним столом. Из знакомых продуктов — с удовольствием.', price='890.00')
        for n, (symbol, title, text) in enumerate([
            ('01', 'Знакомые продукты', 'Без редких ингредиентов и долгих поисков по магазинам.'),
            ('02', 'Понятные шаги', 'Список ингредиентов и последовательность действий в каждом рецепте.'),
            ('03', 'Всегда под рукой', 'Сохраните PDF на телефон, планшет или компьютер.'),
        ]):
            Benefit.objects.create(product=product, symbol=symbol, title=title, text=text, position=n)
        for n, (title, desc, count) in enumerate([
            ('Медленное утро', 'Завтраки, ради которых хочется проснуться', 8),
            ('Ближе к природе', 'Салаты, овощи и простые сочетания', 10),
            ('За одним столом', 'Основные блюда для тёплых встреч', 10),
            ('Что-нибудь сладкое', 'Выпечка и десерты к чашке чая', 8),
        ]):
            Chapter.objects.create(product=product, title=title, description=desc, count=count, position=n)
        recipes = [
            ('Тёплый салат с тыквой', 'Запечённая тыква, нут и сочные томаты с лимонной заправкой.', 35, 'Овощи и салаты', 'img/food.webp', 'Тыква — 400 г\nНут готовый — 200 г\nТоматы черри — 150 г\nРуккола — 50 г\nОливковое масло — 2 ст. л.\nЛимонный сок — 1 ст. л.', 'Нарежьте тыкву и перемешайте с половиной масла.\nЗапекайте при 200 °C около 25 минут до мягкости.\nСоедините с нутом, томатами и рукколой.\nДобавьте оставшееся масло и лимонный сок.'),
            ('Паста с томатами и базиликом', 'Сочный томатный соус, немного оливкового масла и свежая зелень.', 25, 'За одним столом', 'img/pasta.webp', 'Паста — 200 г\nТоматы — 300 г\nЧеснок — 1 зубчик\nБазилик — 1 веточка\nОливковое масло — 1 ст. л.', 'Отварите пасту по инструкции на упаковке.\nПрогрейте чеснок в масле, добавьте томаты.\nТушите около 10 минут.\nСоедините пасту с соусом и базиликом.'),
            ('Галета с грушей', 'Тонкое хрустящее тесто и спелая груша. Хороша ещё тёплой.', 50, 'Что-нибудь сладкое', 'img/galette.webp', 'Мука — 180 г\nСливочное масло — 90 г\nХолодная вода — 4 ст. л.\nГруши — 2 шт.\nСахар — 2 ст. л.', 'Разотрите муку с холодным маслом в крошку.\nДобавьте воду, соберите тесто и охладите 15 минут.\nРаскатайте, выложите груши, посыпьте сахаром и загните края.\nВыпекайте при 190 °C около 30 минут до румяности.'),
        ]
        for n, row in enumerate(recipes):
            title, desc, mins, cat, image, ingredients, steps = row
            Recipe.objects.create(product=product, title=title, description=desc, minutes=mins, category=cat, image_static=image, ingredients=ingredients, instructions=steps, position=n)
        for slug, (title, body) in LEGAL.items():
            LegalPage.objects.get_or_create(slug=slug, defaults={'title': title, 'body': body})
        if options['with_pdf']:
            if not settings.DEBUG:
                raise CommandError('Demo PDF creation requires DEBUG=True.')
            settings.PRIVATE_ROOT.mkdir(parents=True, exist_ok=True)
            path = settings.PRIVATE_ROOT / 'demo.pdf'
            if not path.exists():
                demo_pdf(path)
            product.pdf_name = path.name
            product.save()
        self.stdout.write('Demo content created. Sales remain disabled. Replace all demo materials before launch.')
