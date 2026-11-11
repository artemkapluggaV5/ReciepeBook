import logging
from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST, require_http_methods
from products.models import Product
from payments.providers import PaymentError
from delivery.services import prepare_download
from .forms import CheckoutForm
from .models import Order
from .rate_limit import limited
from .services import create_checkout

logger = logging.getLogger(__name__)


def remember_order(request, order_id):
    owned = request.session.get('orders', [])
    key = str(order_id)
    request.session['orders'] = ([item for item in owned if item != key] + [key])[-20:]


@require_POST
def checkout(request):
    if limited(request, 'checkout'):
        response = render(request, 'message.html', {'title': 'Небольшая пауза', 'text': 'Слишком много попыток. Повторите через 10 минут.'}, status=429)
        response['Retry-After'] = '600'
        return response
    form = CheckoutForm(request.POST)
    product = Product.objects.filter(active=True).first()
    if not product:
        return HttpResponse('Сборник временно недоступен.', status=503)
    if not form.is_valid():
        return render(request, 'landing.html', {'product': product, 'form': form, 'purchase_error': 'Примите условия оферты и повторите попытку.'}, status=400)
    if str(form.cleaned_data['request_key']) != request.session.get('checkout_key'):
        return render(request, 'message.html', {'title': 'Обновите страницу', 'text': 'Откройте главную страницу и отправьте форму снова.'}, status=400)
    try:
        order, url = create_checkout(product, form.cleaned_data['request_key'])
    except PaymentError as exc:
        logger.warning('checkout_error code=%s', str(exc))
        return render(request, 'landing.html', {'product': product, 'form': form, 'purchase_error': 'Оплата сейчас недоступна. Деньги на сайте не списывались. Попробуйте позже или напишите в поддержку.'}, status=503)
    remember_order(request, order.pk)
    return redirect(url or reverse('order-status', args=[order.pk]))


@require_http_methods(['GET', 'HEAD'])
def status(request, order_id):
    if str(order_id) not in request.session.get('orders', []):
        return render(request, 'message.html', {'title': 'Доступ к заказу ограничен',
            'text': 'Откройте страницу в том браузере, где оформляли покупку. Если доступ потерян, сообщите поддержке номер заказа и данные платежа.'}, status=403)
    order = get_object_or_404(Order.objects.select_related('product', 'yookassa_invoice'), pk=order_id)
    if order.status == Order.Status.PENDING and request.method != 'HEAD':
        from payments.services import sync_payment
        try:
            sync_payment(order.pk)
        except PaymentError as exc:
            logger.warning('payment_status_error code=%s', str(exc))
        order.refresh_from_db()
    if order.status == Order.Status.CANCELLED and request.headers.get('Accept') != 'application/json':
        return redirect('payment-fail')
    token, issue = prepare_download(order.pk) if order.status == Order.Status.PAID else (None, '')
    if request.headers.get('Accept') == 'application/json':
        return JsonResponse({'status': order.status, 'ready': bool(token), 'issue': issue})
    return render(request, 'status.html', {'order': order, 'download_token': token,
        'download_issue': issue, 'download_days': settings.DOWNLOAD_DAYS, 'download_limit': settings.DOWNLOAD_LIMIT})
