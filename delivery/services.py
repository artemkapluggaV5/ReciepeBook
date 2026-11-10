import logging
import uuid
from datetime import timedelta
from django.conf import settings
from django.core import signing
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from orders.models import Order

logger = logging.getLogger(__name__)
TOKEN_SALT = 'recipe-shop.download.v1'

def download_token(order):
    return signing.dumps({'order': str(order.pk), 'version': str(order.token_version)}, salt=TOKEN_SALT, compress=False)

def email_service(order):
    context = {'order': order, 'download_url': settings.SITE_URL + reverse('download', args=[download_token(order)]),
               'contact_email': settings.CONTACT_EMAIL, 'days': settings.DOWNLOAD_DAYS, 'limit': settings.DOWNLOAD_LIMIT}
    message = EmailMultiAlternatives(
        subject=f'Ваш сборник «{order.product_title}» — оплата подтверждена',
        body=render_to_string('email/delivery.txt', context), from_email=settings.DEFAULT_FROM_EMAIL,
        to=[order.email], reply_to=[settings.CONTACT_EMAIL],
        headers={'Message-ID': f'<delivery-{order.pk}-{order.token_version}@{settings.SITE_URL.split("://")[-1].split(":")[0]}>'},
    )
    message.attach_alternative(render_to_string('email/delivery.html', context), 'text/html')
    if message.send(fail_silently=False) != 1:
        raise RuntimeError('Email backend did not accept message')

def deliver_order(order_id, force=False, renew=False):
    # PostgreSQL row lock serializes workers and duplicate admin/retry requests.
    # SMTP call is bounded by EMAIL_TIMEOUT. See README for the SMTP crash-window caveat.
    with transaction.atomic():
        order = Order.objects.select_for_update(of=('self',)).select_related('product').get(pk=order_id)
        if order.status != Order.Status.PAID:
            return False
        if order.delivery_status == Order.Delivery.SENT and not force:
            return False
        order.delivery_attempts += 1
        order.last_attempt_at = timezone.now()
        try:
            order.product.private_path()
        except (OSError, ValueError):
            order.delivery_status, order.delivery_error = Order.Delivery.FAILED, 'pdf_missing'
            order.save()
            logger.error('delivery_failed order=%s code=pdf_missing', order.pk)
            return False
        if renew or not order.token_issued_at:
            order.token_version, order.token_issued_at = uuid.uuid4(), timezone.now()
            if renew:
                order.download_count = 0
        try:
            email_service(order)
        except Exception:
            order.delivery_status, order.delivery_error = Order.Delivery.FAILED, 'email_failed'
            order.save()
            logger.error('delivery_failed order=%s code=email_failed', order.pk)
            return False
        order.delivery_status, order.delivery_error = Order.Delivery.SENT, ''
        order.delivered_at = timezone.now()
        order.save()
        return True

def due_orders():
    for order in Order.objects.filter(status=Order.Status.PAID).exclude(delivery_status=Order.Delivery.SENT).iterator(chunk_size=50):
        # Exponential backoff, max 8 automatic attempts; admin can retry after remediation.
        if order.delivery_attempts >= 8:
            continue
        delay = timedelta(seconds=min(3600, 30 * 2 ** min(order.delivery_attempts, 7)))
        if not order.last_attempt_at or order.last_attempt_at < timezone.now() - delay:
            yield order.pk
