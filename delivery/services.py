"""Private PDF access for verified paid orders. No outbound email."""
import logging
import uuid
from datetime import timedelta
from django.conf import settings
from django.core import signing
from django.db import transaction
from django.utils import timezone
from orders.models import Order

logger = logging.getLogger(__name__)
TOKEN_SALT = 'recipe-shop.download.v1'


def download_token(order):
    return signing.dumps({'order': str(order.pk), 'version': str(order.token_version)},
                         salt=TOKEN_SALT, compress=False)


def prepare_download(order_id):
    """Call after browser ownership checks. Never renew expired access implicitly."""
    with transaction.atomic():
        order = Order.objects.select_for_update(of=('self',)).select_related('product').get(pk=order_id)
        if order.status != Order.Status.PAID:
            return None, 'unpaid'
        try:
            order.product.private_path()
        except (OSError, ValueError):
            logger.error('download_failed order=%s code=pdf_missing', order.pk)
            return None, 'pdf_missing'
        if not order.token_issued_at:
            order.token_issued_at = timezone.now()
            order.save(update_fields=['token_issued_at', 'updated_at'])
        if (order.token_issued_at < timezone.now() - timedelta(days=settings.DOWNLOAD_DAYS)
                or order.download_count >= settings.DOWNLOAD_LIMIT):
            return None, 'expired'
        return download_token(order), ''


def renew_download(order_id):
    """Staff-only recovery, after checking the customer's payment reference."""
    with transaction.atomic():
        order = Order.objects.select_for_update(of=('self',)).get(pk=order_id)
        if order.status != Order.Status.PAID:
            return False
        order.token_version = uuid.uuid4()
        order.token_issued_at = timezone.now()
        order.download_count = 0
        order.save(update_fields=['token_version', 'token_issued_at', 'download_count', 'updated_at'])
        return True
