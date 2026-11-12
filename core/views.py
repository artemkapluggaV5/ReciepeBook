import uuid
import re
from django.conf import settings
from django.db import connection
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_safe
from orders.forms import CheckoutForm
from orders.models import Order
from products.models import Product
from .models import LegalPage
from payments.receipts import receipts_enabled

def csrf_failure(request, reason=''):
    return render(request, 'message.html', {'title': 'Обновите страницу', 'text': 'Защитный код формы устарел или запрос пришёл с другого сайта. Вернитесь на главную и отправьте форму снова.'}, status=403)

@require_safe
def landing(request):
    product = Product.objects.filter(active=True).prefetch_related('benefits','chapters','recipes','previews').first()
    if not product:
        return render(request, 'message.html', {'title': 'Скоро будет вкусно', 'text': 'Сборник готовится к публикации. Заходите позже.'}, status=503)
    old_key = request.session.get('checkout_key')
    complete = old_key and Order.objects.filter(request_key=old_key, status__in=['paid','refunded','cancelled']).exists()
    legacy = old_key and Order.objects.filter(request_key=old_key).exclude(provider='yookassa').exists()
    changed_configuration = old_key and Order.objects.filter(request_key=old_key,
        yookassa_invoice__isnull=False).exclude(
            yookassa_invoice__test_mode=settings.YOOKASSA_TEST_MODE,
            yookassa_invoice__shop_id=settings.YOOKASSA_SHOP_ID).exists()
    receipt_mode_changed = request.session.get('checkout_receipts') != receipts_enabled()
    if not old_key or complete or legacy or changed_configuration or receipt_mode_changed:
        request.session['checkout_key'] = str(uuid.uuid4())
        request.session['checkout_receipts'] = receipts_enabled()
    form = CheckoutForm(initial={'request_key': request.session['checkout_key']})
    return render(request, 'landing.html', {'product': product, 'form': form, 'payment_failed': request.session.pop('payment_failed', False)})

@require_safe
def legal(request, slug):
    page = get_object_or_404(LegalPage, slug=slug)
    paragraphs = [p.strip() for p in re.split(r'\n\s*\n', page.body) if p.strip()]
    legal_blocks = [{'text': text, 'heading': bool(re.match(r'^\d+\.\s+\D', text))
                     and len(text) < 100} for text in paragraphs]
    return render(request, 'legal.html', {'page': page, 'legal_blocks': legal_blocks})

@require_safe
def health(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
    except Exception:
        return HttpResponse('unavailable', status=503, content_type='text/plain')
    return HttpResponse('ok', content_type='text/plain')

@require_safe
def robots(request):
    text = 'User-agent: *\nDisallow: /\n'
    if settings.SALES_ENABLED:
        text = f'User-agent: *\nDisallow: /admin/\nDisallow: /download/\nDisallow: /order/\nDisallow: /checkout/\nDisallow: /payments/\nSitemap: {settings.SITE_URL}/sitemap.xml\n'
    return HttpResponse(text, content_type='text/plain; charset=utf-8')

@require_safe
def sitemap(request):
    return render(request, 'sitemap.xml', content_type='application/xml')
