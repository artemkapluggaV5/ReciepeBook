from pathlib import Path
from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, FileExtensionValidator
from django.db import models

class Product(models.Model):
    title = models.CharField('Название', max_length=180, default='Марина Новикова')
    subtitle = models.CharField('Подзаголовок', max_length=220, default='Простые рецепты. Особенные моменты.')
    description = models.TextField('Описание')
    price = models.DecimalField('Цена', max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal('1'))])
    currency = models.CharField(max_length=3, default='RUB', choices=[('RUB', 'Российский рубль')])
    cover = models.FileField('Обложка', upload_to='covers/', blank=True, validators=[FileExtensionValidator(['jpg','jpeg','png','webp'])])
    cover_static = models.CharField(max_length=200, default='img/food.webp')
    recipe_count = models.PositiveIntegerField('Число рецептов', default=36)
    page_count = models.PositiveIntegerField('Число страниц', default=72)
    pdf_name = models.CharField('Имя PDF внутри PRIVATE_ROOT', max_length=180, blank=True)
    bonus_pdf_name = models.CharField('Подарочный PDF внутри PRIVATE_ROOT', max_length=180, blank=True)
    bonus_title = models.CharField('Название подарка', max_length=180, default='Маришкины рецепты', blank=True)
    active = models.BooleanField('Показывать на сайте', default=True)
    is_demo = models.BooleanField('Демонстрационные материалы', default=True)
    updated_at = models.DateTimeField(auto_now=True)
    def clean(self):
        for field in ('pdf_name', 'bonus_pdf_name'):
            name = getattr(self, field)
            if name and (Path(name).name != name or not name.lower().endswith('.pdf') or '\\' in name):
                raise ValidationError({field: 'Укажите только имя PDF без пути.'})
    def private_path(self, asset='main'):
        if asset not in ('main', 'bonus'):
            raise ValueError('Unknown PDF asset')
        name = self.bonus_pdf_name if asset == 'bonus' else self.pdf_name
        if not name or Path(name).name != name or '\\' in name:
            raise ValueError('PDF is not configured')
        root = settings.PRIVATE_ROOT.resolve()
        path = (root / name).resolve()
        if path.parent != root or path.suffix.lower() != '.pdf' or not path.is_file():
            raise ValueError('Private PDF missing or invalid')
        with path.open('rb') as stream:
            if stream.read(5) != b'%PDF-':
                raise ValueError('Invalid PDF header')
        return path
    def __str__(self):
        return self.title

    @property
    def public_reviews(self):
        return self.reviews.filter(published=True)

class Benefit(models.Model):
    product = models.ForeignKey(Product, related_name='benefits', on_delete=models.CASCADE)
    symbol = models.CharField(max_length=8, default='↗')
    title = models.CharField(max_length=120)
    text = models.TextField()
    position = models.PositiveIntegerField(default=0)
    class Meta:
        ordering = ['position', 'pk']

class Chapter(models.Model):
    product = models.ForeignKey(Product, related_name='chapters', on_delete=models.CASCADE)
    title = models.CharField(max_length=140)
    description = models.CharField(max_length=220)
    count = models.PositiveIntegerField(default=0)
    position = models.PositiveIntegerField(default=0)
    class Meta:
        ordering = ['position', 'pk']

class Recipe(models.Model):
    product = models.ForeignKey(Product, related_name='recipes', on_delete=models.CASCADE)
    title = models.CharField(max_length=160)
    description = models.TextField()
    minutes = models.PositiveIntegerField(default=25)
    category = models.CharField(max_length=80)
    image = models.FileField(upload_to='recipes/', blank=True, validators=[FileExtensionValidator(['jpg','jpeg','png','webp'])])
    image_static = models.CharField(max_length=200, default='img/food.webp')
    included_in_pdf = models.BooleanField('Подтверждено наличие в PDF', default=False)
    ingredients = models.TextField('Ингредиенты (строка на пункт)', blank=True)
    instructions = models.TextField('Приготовление (строка на шаг)', blank=True)
    position = models.PositiveIntegerField(default=0)
    class Meta:
        ordering = ['position', 'pk']

class Preview(models.Model):
    product = models.ForeignKey(Product, related_name='previews', on_delete=models.CASCADE)
    title = models.CharField(max_length=120)
    image = models.FileField(upload_to='previews/', validators=[FileExtensionValidator(['jpg','jpeg','png','webp'])])
    position = models.PositiveIntegerField(default=0)
    class Meta:
        ordering = ['position', 'pk']

class Review(models.Model):
    product = models.ForeignKey(Product, related_name='reviews', on_delete=models.CASCADE)
    author = models.CharField('Имя автора', max_length=120)
    text = models.TextField('Текст отзыва')
    image = models.FileField('Фото (необязательно)', upload_to='reviews/', blank=True,
        validators=[FileExtensionValidator(['jpg', 'jpeg', 'png', 'webp'])])
    published = models.BooleanField('Разрешение на публикацию получено', default=False)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['position', 'pk']
        verbose_name = 'отзыв'
        verbose_name_plural = 'отзывы'

    def __str__(self):
        return self.author
