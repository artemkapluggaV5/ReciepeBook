from django.conf import settings
def site_context(request):
    return {'site_url': settings.SITE_URL, 'contact_email': settings.CONTACT_EMAIL,
            'merchant_name': settings.MERCHANT_NAME, 'merchant_details': settings.MERCHANT_DETAILS,
            'sales_enabled': settings.SALES_ENABLED,
            'payment_test_mode': settings.ROBOKASSA_TEST_MODE}
