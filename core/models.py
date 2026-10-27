from django.db import models

class LegalPage(models.Model):
    slug = models.SlugField(unique=True)
    title = models.CharField(max_length=160)
    body = models.TextField('Текст (обычный текст, абзацы через пустую строку)')
    is_draft = models.BooleanField('Шаблон, требует проверки', default=True)
    updated_at = models.DateTimeField(auto_now=True)
    def __str__(self):
        return self.title
