import logging
from django.db import IntegrityError
from django.http import HttpResponse, QueryDict
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from .services import process_result, validate_event, RejectedEvent, InvalidSignature

logger = logging.getLogger(__name__)

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

# Read-only redirects: POST needs no CSRF because it never changes payment state.
# A cross-site POST on iOS need not carry the SameSite=Lax session cookie.
@csrf_exempt
@require_http_methods(['GET', 'POST'])
def success(request):
    try:
        invoice = validate_event(parameters(request), success_redirect=True)
    except (RejectedEvent, UnicodeDecodeError):
        return render(request, 'message.html', {'title': 'Не удалось проверить возврат',
            'text': 'Откройте письмо с подтверждением или обратитесь в поддержку.'}, status=400)
    return render(request, 'status.html', {'order': invoice.order, 'payment_return': True})

@csrf_exempt
@require_http_methods(['GET', 'POST'])
def fail(request):
    # FailURL is not an authenticated failure callback. Never downgrade a paid order.
    return render(request, 'message.html', {'title': 'Оплата не завершена',
        'text': 'Вы вернулись со страницы оплаты. Если деньги списались, дождитесь подтверждения и письма. Иначе можно повторить оформление на главной.'})
