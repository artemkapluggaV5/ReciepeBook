import logging
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST, require_http_methods
from products.models import Product
from payments.providers import PaymentError
from .forms import CheckoutForm
from .models import Order
from .rate_limit import limited
from .services import create_checkout

logger = logging.getLogger(__name__)

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
        return render(request, 'landing.html', {'product': product, 'form': form, 'purchase_error': 'Проверьте email и согласие с условиями.'}, status=400)
    if str(form.cleaned_data['request_key']) != request.session.get('checkout_key'):
        return render(request, 'message.html', {'title': 'Обновите страницу', 'text': 'Откройте главную страницу и отправьте форму снова.'}, status=400)
    try:
        order, url = create_checkout(product, form.cleaned_data['email'], form.cleaned_data['request_key'])
    except PaymentError as exc:
        # Only a controlled error code, never provider payload, credentials or customer email.
        logger.warning('checkout_error code=%s', str(exc))
        return render(request, 'landing.html', {'product': product, 'form': form, 'purchase_error': 'Оплата сейчас недоступна. Деньги на сайте не списывались. Попробуйте позже или напишите в поддержку.'}, status=503)
    owned = request.session.get('orders', [])
    request.session['orders'] = (owned + [str(order.pk)])[-10:]
    return redirect(url or reverse('order-status', args=[order.pk]))

@require_http_methods(['GET', 'HEAD'])
def status(request, order_id):
    # No email or download capability on the return URL. Only the creating session sees status.
    if str(order_id) not in request.session.get('orders', []):
        return render(request, 'message.html', {'title': 'Проверяем оплату', 'text': 'После подтверждения оплаты письмо придёт на указанный email. При затруднениях обратитесь в поддержку.'})
    order = get_object_or_404(Order, pk=order_id)
    return render(request, 'status.html', {'order': order})

