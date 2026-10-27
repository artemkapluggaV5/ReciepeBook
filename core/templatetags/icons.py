"""Font-independent inline icons; no sprites, fonts, masks or external URLs."""
from django import template
from django.utils.html import format_html
from django.utils.safestring import mark_safe

register = template.Library()
PATHS = {
    'arrow': '<path d="M5 19 19 5M5 5h14v14"/>',
    'down': '<path d="M12 4v16M5 13l7 7 7-7"/>',
    'mail': '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 6 9 7 9-7"/>',
    'menu': '<path d="M4 6h16M4 12h16M4 18h16"/>',
    'clock': '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    'lock': '<rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/>',
    'check': '<path d="m5 12 4 4L19 6"/>',
    'plus': '<path d="M12 5v14M5 12h14"/>',
    'refresh': '<path d="M20 11a8 8 0 1 0-2 6M20 4v7h-7"/>',
    'flower': '<path d="M12 2v20M2 12h20M5 5l14 14M5 19 19 5"/>',
}

@register.simple_tag
def icon(name):
    paths = PATHS.get(name, PATHS['flower'])
    return format_html('<svg xmlns="http://www.w3.org/2000/svg" class="icon icon-{}" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">{}</svg>', name if name in PATHS else 'flower', mark_safe(paths))

@register.simple_tag
def benefit_marker(value):
    if str(value).isascii() and str(value).isdigit():
        return format_html('{}', value)
    return icon('arrow')
