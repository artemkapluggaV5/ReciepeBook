import json
import logging
import uuid
from django.core import signing
from django.http import HttpResponse
from django.shortcuts import render, redirect
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_safe
from orders.models import Order
from orders.views import remember_order
from .providers import PaymentError, RETURN_SALT, valid_payment_id
from .services import sync_payment, process_refund

logger = logging.getLogger(__name__)

@csrf_exempt
@require_POST
def webhook(request):
    if request.content_type != 'application/json':
        return HttpResponse(status=400)
    try:
        event = json.loads(request.body)
        if not isinstance(event, dict) or event.get('type') != 'notification':
            return HttpResponse(status=400)
        kind = event.get('event')
        if kind not in {'payment.succeeded', 'payment.canceled', 'payment.waiting_for_capture', 'refund.succeeded'}:
            return HttpResponse(status=200)
        obj = event.get('object')
        if not isinstance(obj, dict) or not valid_payment_id(obj.get('id')):
            return HttpResponse(status=400)
        payment_id = obj.get('payment_id') if kind == 'refund.succeeded' else obj['id']
        # Unknown IDs must not trigger arbitrary authenticated API queries.
        order = Order.objects.filter(provider='yookassa', provider_payment_id=payment_id).first()
        if not order:
            return HttpResponse(status=200)
        if kind == 'refund.succeeded':
            process_refund(obj['id'], order.pk)
        else:
            sync_payment(order.pk, force=True)
    except (ValueError, UnicodeError):
        return HttpResponse(status=400)
    except PaymentError as exc:
        logger.warning('yookassa_verification_error code=%s', str(exc))
        return HttpResponse(status=503)
    return HttpResponse(status=200)

@require_safe
def payment_return(request):
    try:
        order_id = uuid.UUID(signing.loads(request.GET.get('token', ''), salt=RETURN_SALT, max_age=86400*7))
        order = Order.objects.get(pk=order_id, provider='yookassa')
    except (signing.BadSignature, ValueError, TypeError, Order.DoesNotExist):
        return render(request, 'message.html', {'title':'Не удалось проверить возврат',
            'text':'Откройте страницу заказа в браузере покупки или напишите в поддержку.'}, status=400)
    # The signed return only restores ownership. API verification in status
    # independently confirms payment; URL/query parameters can never mark paid.
    remember_order(request, order.pk)
    return redirect('order-status', order_id=order.pk)

@require_safe
def fail(request):
    return render(request, 'payment_failed.html')
