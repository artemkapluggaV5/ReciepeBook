"""Update DEMO presentation using existing product fields, without schema changes."""
from pathlib import Path
from django.conf import settings
from django.core import serializers
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from products.models import Product

class Command(BaseCommand):
    help = 'Apply holiday presentation to an active demo product; preserve price, PDF, uploads and verified recipes.'
    def add_arguments(self, parser):
        parser.add_argument('--backup', help='JSON backup path. Defaults to ignored work/ inside the project.')

    @transaction.atomic
    def handle(self, *args, **options):
        product = Product.objects.select_for_update().filter(active=True, is_demo=True).first()
        if not product:
            self.stdout.write('Активный демопродукт не найден. Реальные товары не изменены; используйте существующий Admin.')
            return
        related = [*product.benefits.all(), *product.chapters.all(), *product.recipes.all()]
        backup = Path(options['backup']) if options.get('backup') else settings.BASE_DIR / 'work' / ('holiday-before-' + timezone.now().strftime('%Y%m%d-%H%M%S-%f') + '.json')
        backup.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation prevents accidental overwrite of the previous snapshot.
        with backup.open('x', encoding='utf-8') as stream:
            stream.write(serializers.serialize('json', [product, *related], ensure_ascii=False, indent=2))
        product.title = 'Новогодний сборник рецептов'
        product.subtitle = 'Для вечеров, которые становятся воспоминаниями'
        product.description = 'Праздничные идеи для красивого стола, тёплых встреч и долгих разговоров. Соберите близких — и добавьте немного домашнего волшебства.'
        product.cover_static = 'img/holiday-main.webp'
        product.save(update_fields=['title', 'subtitle', 'description', 'cover_static', 'updated_at'])
        benefits = [
            ('Красивое начало', 'Закуски, салаты и праздничная подача — идеи для первого впечатления за столом.'),
            ('Тёплая встреча', 'Вдохновение для главного блюда и уютного вечера с теми, кто вам дорог.'),
            ('Сладкие воспоминания', 'Десерты и небольшие детали, которые продлевают ощущение праздника.'),
        ]
        for row, (title, text) in zip(product.benefits.all(), benefits):
            row.title, row.text = title, text
            row.save(update_fields=['title', 'text'])
        chapters = [
            ('Первые минуты праздника', 'Закуски и салаты для красивого начала'),
            ('В центре стола', 'Идеи для главного праздничного блюда'),
            ('Сладкий финал', 'Зимние десерты к долгим разговорам'),
            ('Маленькие детали', 'Вдохновение для подачи и домашнего настроения'),
        ]
        for row, (title, text) in zip(product.chapters.all(), chapters):
            row.title, row.description = title, text
            row.save(update_fields=['title', 'description'])
        recipes = [
            ('Брускетты со свёклой и мягким сыром', 'Нежный сыр, запечённая свёкла, орехи и свежий тимьян.', 25, 'Праздничные закуски', 'img/holiday-appetizer.webp',
             'Багет\nГотовая запечённая свёкла\nСливочный сыр\nГрецкие орехи\nТимьян',
             'Подрумяньте ломтики багета.\nНарежьте готовую запечённую свёклу небольшими кубиками.\nНанесите сыр, добавьте свёклу, орехи и тимьян.\nЭто иллюстративная идея подачи; пропорции и время уточнит автор.'),
            ('Утка с апельсином и клюквой', 'Праздничное сочетание цитрусов, ягодного соуса и ароматных трав.', 50, 'Главное блюдо', 'img/holiday-main.webp',
             'Утиная грудка\nАпельсин\nКлюква\nТимьян\nОвощи для гарнира',
             'Иллюстративная идея праздничной подачи.\nПриготовьте утиную грудку по проверенной рецептуре до полной готовности.\nПодайте с апельсином, клюквенным соусом и овощами.\nТочные пропорции и способ приготовления должен проверить автор перед публикацией.'),
            ('Шоколадный десерт с клюквой', 'Тёплый шоколад, воздушный крем и яркая зимняя ягода.', 30, 'Сладкий финал', 'img/holiday-dessert.webp',
             'Тёмный шоколад\nИнгредиенты для шоколадной основы\nСливочный крем\nКлюква',
             'Иллюстративный пример оформления десерта.\nПриготовьте шоколадную основу по проверенной рецептуре.\nДополните кремом и ягодами перед подачей.\nРецептура и время демонстрационные; наличие в PDF не подтверждено.'),
        ]
        for row, data in zip(product.recipes.all(), recipes):
            # Do not overwrite a recipe the owner has explicitly verified against the PDF.
            if row.included_in_pdf:
                continue
            row.title, row.description, row.minutes, row.category, row.image_static, row.ingredients, row.instructions = data
            row.save(update_fields=['title','description','minutes','category','image_static','ingredients','instructions'])
        self.stdout.write('Новогодняя демопрезентация сохранена. Цена, PDF, загруженные файлы и подтверждённые рецепты не изменены.')
