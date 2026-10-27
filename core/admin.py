from django.contrib import admin
from .models import LegalPage
@admin.register(LegalPage)
class LegalPageAdmin(admin.ModelAdmin):
    list_display = ['title', 'slug', 'is_draft', 'updated_at']
    list_filter = ['is_draft']
    search_fields = ['title', 'body']
