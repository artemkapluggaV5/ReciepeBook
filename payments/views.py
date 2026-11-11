import logging
from django.db import IntegrityError
from django.http import HttpResponse, QueryDict
from django.shortcuts import render, redirect
from orders.views import remember_order
from orders.models import Order
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from .services import process_result, validate_event, RejectedEvent, InvalidSignature

logger = logging.getLogger(__name__)

@require_http_methods(['GET', 'HEAD'])
def widget_check(request):
    # This cabinet-created invoice has no local order binding.
    # Never grant downloads or relax ResultURL verification for it.
    return render(request, 'payment_widget_check.html')


def parameters(request):
    if request.method == 'POST':
        if request.content_type != 'application/x-www-form-urlencoded' or request.GET:
            raise RejectedEvent
        event = QueryDict(request.body, encoding='utf-8')
    else:
        event = request.GET
    if any(len(values) != 1 for _, values in event.lists()):
        raise RejectedEvent
    return event

# Server-to-server callback. Robokassa's documented signature replaces CSRF ONLY here.
# Continue settling existing invoices when new sales are disabled for maintenance.
@csrf_exempt
@require_http_methods(['POST', 'GET'])
def result(request):
    try:
        number = process_result(parameters(request))
    except InvalidSignature:
        logger.warning('robokassa_result_rejected reason=signature')
        return HttpResponse('Invalid signature', status=403, content_type='text/plain')
    except (RejectedEvent, IntegrityError, UnicodeDecodeError):
        logger.warning('robokassa_result_rejected reason=parameters')
        return HttpResponse('Invalid payment', status=400, content_type='text/plain')
    return HttpResponse(f'OK{number}', content_type='text/plain')

# Robokassa may return via cross-site POST without a SameSite=Lax cookie.
# A verified Password1 signature grants access to THIS order only, never confirms payment.
@csrf_exempt
@require_http_methods(['GET', 'POST'])
def success(request):
    try:
        invoice = validate_event(parameters(request), success_redirect=True)
    except (RejectedEvent, UnicodeDecodeError):
        return render(request, 'message.html', {'title': 'Не удалось проверить возврат',
            'text': 'Вернитесь на страницу заказа в браузере покупки или обратитесь в поддержку.'}, status=400)
    remember_order(request, invoice.order_id)
    return redirect('order-status', order_id=invoice.order_id)


@csrf_exempt
@require_http_methods(['GET', 'POST'])
def fail(request):
    # FailURL is unsigned: never mark failure or grant access from InvId alone.
    event = request.POST if request.method == 'POST' else request.GET
    owned = request.session.get('orders', [])
    paid = Order.objects.filter(pk__in=owned, status=Order.Status.PAID)
    if event.get('InvId'):
        paid = paid.filter(robokassa_invoice__id__in=[event['InvId']] if event['InvId'].isdigit() and len(event['InvId']) <= 18 else [])
    else:
        paid = paid.order_by('-created_at')
    order = paid.first()
    if order:
        return redirect('order-status', order_id=order.pk)
    return render(request, 'payment_failed.html')
