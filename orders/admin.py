from django.contrib import admin, messages
from delivery.services import deliver_order
from .models import Order
@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ['id', 'email', 'provider', 'invoice_number', 'payment_mode', 'amount', 'status', 'delivery_status', 'delivery_attempts', 'created_at']
    list_filter = ['status', 'delivery_status', 'provider', 'robokassa_invoice__test_mode', 'created_at']
    search_fields = ['id', 'email', 'provider_payment_id', 'transaction_id']
    readonly_fields = [f.name for f in Order._meta.fields]
    actions = ['resend', 'renew']
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('robokassa_invoice')
    @admin.display(description='Robokassa InvId')
    def invoice_number(self, obj):
        invoice = getattr(obj, 'robokassa_invoice', None)
        return invoice.pk if invoice else '—'
    @admin.display(description='Режим оплаты')
    def payment_mode(self, obj):
        invoice = getattr(obj, 'robokassa_invoice', None)
        return ('Тестовый' if invoice.test_mode else 'Боевой') if invoice else 'Исторический заказ'
    def has_add_permission(self, request):
        return False
    def has_delete_permission(self, request, obj=None):
        return False
    @admin.action(description='Повторно отправить письмо оплаченным заказам')
    def resend(self, request, queryset):
        sent = sum(deliver_order(o.pk, force=True) for o in queryset)
        self.message_user(request, f'Передано сервису отправки писем: {sent}. Проверьте статусы остальных.', messages.INFO)
    @admin.action(description='Обновить ссылку и отправить письмо (старая ссылка отзывается)')
    def renew(self, request, queryset):
        sent = sum(deliver_order(o.pk, force=True, renew=True) for o in queryset)
        self.message_user(request, f'Передано сервису отправки писем: {sent}.', messages.INFO)
