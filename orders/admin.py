from django.conf import settings
from django.contrib import admin, messages
from django.urls import reverse
from django.utils.html import format_html
from delivery.services import prepare_download, renew_download
from .models import Order

@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ['id', 'provider', 'invoice_number', 'payment_mode', 'amount', 'status', 'download_count', 'created_at']
    list_filter = ['status', 'provider', 'robokassa_invoice__test_mode', 'created_at']
    search_fields = ['id', 'provider_payment_id', 'transaction_id']
    readonly_fields = [f.name for f in Order._meta.fields]
    actions = ['download_links', 'renew']

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

    @admin.action(description='Показать ссылки оплаченных заказов (передавать только покупателю)')
    def download_links(self, request, queryset):
        for order in queryset:
            token, issue = prepare_download(order.pk)
            if token:
                url = settings.SITE_URL + reverse('download', args=[token])
                self.message_user(request, format_html('Заказ {}: <a href="{}">Скачать сборник</a>', order.pk, url))
            else:
                self.message_user(request, f'Заказ {order.pk}: доступ не выдан ({issue}).', messages.WARNING)

    @admin.action(description='Обновить доступ оплаченным заказам (прежняя ссылка отзывается)')
    def renew(self, request, queryset):
        count = sum(renew_download(order.pk) for order in queryset)
        self.message_user(request, f'Обновлён доступ: {count}. Используйте действие «Показать ссылки».')
