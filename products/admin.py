from django.contrib import admin
from .models import Product, Benefit, Chapter, Recipe, Preview, Review
class BenefitInline(admin.TabularInline):
    model = Benefit
    extra = 0
class ChapterInline(admin.TabularInline):
    model = Chapter
    extra = 0
class RecipeInline(admin.StackedInline):
    model = Recipe
    extra = 0
class PreviewInline(admin.TabularInline):
    model = Preview
    extra = 0
class ReviewInline(admin.StackedInline):
    model = Review
    extra = 0
@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ['title', 'price', 'currency', 'active', 'is_demo']
    list_filter = ['active', 'is_demo']
    search_fields = ['title']
    inlines = [BenefitInline, ChapterInline, RecipeInline, PreviewInline, ReviewInline]
