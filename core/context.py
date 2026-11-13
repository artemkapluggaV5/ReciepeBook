from django.conf import settings
from orders.access import purchased_order
def site_context(request):
    return {'purchased_order': purchased_order(request),
            'site_name': settings.SITE_NAME, 'site_url': settings.SITE_URL, 'contact_email': settings.CONTACT_EMAIL,
            'merchant_name': settings.MERCHANT_NAME, 'merchant_details': settings.MERCHANT_DETAILS,
            'seller_display_name': settings.SELLER_DISPLAY_NAME,
            'seller_inn': settings.SELLER_INN, 'seller_ogrn': settings.SELLER_OGRN,
            'sales_enabled': settings.SALES_ENABLED,
            'payment_test_mode': settings.YOOKASSA_TEST_MODE,
            'telegram_username': settings.TELEGRAM_USERNAME,
            'telegram_support_username': settings.TELEGRAM_SUPPORT_USERNAME}
