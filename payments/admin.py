from django.contrib import admin
from .models import PaymentEvent, RobokassaInvoice

@admin.register(RobokassaInvoice)
class RobokassaInvoiceAdmin(admin.ModelAdmin):
    list_display = ['id', 'order', 'merchant_login', 'test_mode', 'currency', 'hash_algorithm', 'created_at']
    list_filter = ['test_mode', 'created_at']
    search_fields = ['id', 'order__id', 'order__email']
    readonly_fields = [f.name for f in RobokassaInvoice._meta.fields]
    def has_add_permission(self, request):
        return False
    def has_delete_permission(self, request, obj=None):
        return False
@admin.register(PaymentEvent)
class EventAdmin(admin.ModelAdmin):
    list_display = ['order', 'kind', 'transaction_id', 'amount', 'created_at']
    list_filter = ['kind', 'created_at']
    search_fields = ['transaction_id', 'order__id']
    readonly_fields = [f.name for f in PaymentEvent._meta.fields]
    def has_add_permission(self, request):
        return False
    def has_delete_permission(self, request, obj=None):
        return False
