from django.contrib import admin
from .models import PaymentEvent, LegacyInvoice, YooKassaInvoice

class ReadOnlyAdmin(admin.ModelAdmin):
    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in self.model._meta.fields]
    def has_add_permission(self, request):
        return False
    def has_delete_permission(self, request, obj=None):
        return False

@admin.register(LegacyInvoice)
class LegacyInvoiceAdmin(ReadOnlyAdmin):
    list_display = ['id', 'order', 'merchant_login', 'test_mode', 'created_at']
    search_fields = ['order__id']

@admin.register(YooKassaInvoice)
class YooKassaInvoiceAdmin(ReadOnlyAdmin):
    list_display = ['order', 'shop_id', 'test_mode', 'last_checked_at', 'created_at']
    search_fields = ['order__id']
    exclude = ['return_url']

@admin.register(PaymentEvent)
class EventAdmin(ReadOnlyAdmin):
    list_display = ['order', 'kind', 'transaction_id', 'amount', 'created_at']
    list_filter = ['kind', 'created_at']
    search_fields = ['transaction_id', 'order__id']
