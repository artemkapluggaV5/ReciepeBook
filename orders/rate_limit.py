from datetime import timedelta
from django.db import transaction
from django.conf import settings
from django.utils import timezone
from django.utils.crypto import salted_hmac
from .models import RateBucket
def limited(request, scope, limit=10, seconds=600):
    address = request.META.get('REMOTE_ADDR', 'unknown')
    if settings.TRUST_PROXY:
        address = request.META.get('HTTP_X_REAL_IP', address)
    key = salted_hmac('rate', scope + ':' + address).hexdigest()
    now = timezone.now()
    with transaction.atomic():
        RateBucket.objects.get_or_create(key=key, defaults={'start': now})
        bucket = RateBucket.objects.select_for_update().get(key=key)
        if bucket.start < now - timedelta(seconds=seconds):
            bucket.start, bucket.count = now, 0
        if bucket.count >= limit:
            return True
        bucket.count += 1
        bucket.save(update_fields=['start', 'count'])
    return False
