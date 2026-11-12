import secrets
import logging
from datetime import timedelta
from django.conf import settings
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import FileResponse, HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from orders.models import Order
from orders.rate_limit import limited
from .services import TOKEN_SALT
logger = logging.getLogger(__name__)

@require_http_methods(['GET', 'HEAD'])
def download(request, token):
    if limited(request, 'download', limit=60, seconds=600):
        return HttpResponse('Слишком много запросов. Повторите позже.', status=429)
    try:
        if len(token) > 600:
            raise ValueError
        payload = signing.loads(token, salt=TOKEN_SALT)
        if payload['order'] not in request.session.get('orders', []):
            return render(request, 'message.html', {'title': 'Доступ к скачиванию ограничен',
                'text': 'Откройте ссылку в том браузере, где оформляли покупку. Если доступ потерян, напишите в поддержку с номером заказа и данными платежа.'}, status=403)
        with transaction.atomic():
            order = Order.objects.select_for_update(of=('self',)).select_related('product').get(pk=payload['order'])
            if order.status != Order.Status.PAID or not order.token_issued_at:
                raise ValueError
            if not secrets.compare_digest(str(order.token_version), str(payload['version'])):
                raise ValueError
            if order.token_issued_at < timezone.now() - timedelta(days=settings.DOWNLOAD_DAYS) or order.download_count >= settings.DOWNLOAD_LIMIT:
                return render(request, 'message.html', {'title': 'Обновим вашу ссылку', 'text': 'Срок или лимит ссылки закончился. Сообщите поддержке номер заказа и данные платежа — мы поможем восстановить доступ.'}, status=410)
            try:
                stream = order.product.private_path().open('rb')
            except (ValueError, OSError):
                logger.error('download_failed order=%s code=pdf_missing', order.pk)
                return render(request, 'message.html', {'title': 'Файл временно недоступен', 'text': 'Оплата сохранена. Напишите в поддержку — мы восстановим выдачу.'}, status=503)
            if request.method == 'GET':
                order.download_count += 1
                order.save(update_fields=['download_count', 'updated_at'])
            response = FileResponse(stream, as_attachment=True, filename='cookbook.pdf', content_type='application/pdf')
            response['Cache-Control'] = 'private, no-store'
            response['X-Robots-Tag'] = 'noindex, nofollow'
            return response
    except (signing.BadSignature, Order.DoesNotExist, ValidationError, ValueError, KeyError, TypeError):
        return render(request, 'message.html', {'title': 'Ссылка недоступна', 'text': 'Откройте страницу своего заказа или обратитесь в поддержку.'}, status=404)
