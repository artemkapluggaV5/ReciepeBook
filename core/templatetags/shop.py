from django import template
from django.templatetags.static import static
register = template.Library()
@register.simple_tag
def asset(path):
    try:
        return static(path)
    except (ValueError, TypeError):
        return static('img/food.webp')
