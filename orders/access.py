"""Storefront purchase state is derived from verified orders in this browser."""
import uuid

from products.models import Product
from .models import Order


def purchased_order(request, product=None):
    owned = request.session.get('orders', [])
    if not isinstance(owned, (list, tuple)):
        return None
    ids = []
    for value in owned[-40:]:
        try:
            ids.append(uuid.UUID(str(value)))
        except (ValueError, TypeError, AttributeError):
            continue
    if not ids:
        return None
    request._has_purchase_history = True
    if product is not None:
        product_id = product.pk
        request._storefront_product_id = product_id
    else:
        product_id = getattr(request, '_storefront_product_id', None)
        if product_id is None:
            product_id = Product.objects.filter(active=True).order_by('pk').values_list('pk', flat=True).first()
            request._storefront_product_id = product_id
    if product_id is None:
        return None
    cache = getattr(request, '_purchased_order_cache', {})
    if product_id not in cache:
        cache[product_id] = (Order.objects.filter(pk__in=ids, product_id=product_id, status=Order.Status.PAID)
            .order_by('-paid_at', '-created_at').first())
        request._purchased_order_cache = cache
    return cache[product_id]
