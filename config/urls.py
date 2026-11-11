from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path
from core import views
from orders.views import checkout, status
from payments.views import webhook, payment_return, fail
from delivery.views import download

urlpatterns = [
    path('admin/', admin.site.urls), path('', views.landing, name='landing'),
    path('health/', views.health, name='health'), path('legal/<slug:slug>/', views.legal, name='legal'),
    path('checkout/', checkout, name='checkout'), path('order/<uuid:order_id>/', status, name='order-status'),
    path('payments/yookassa/webhook/', webhook, name='yookassa-webhook'),
    path('payments/yookassa/return/', payment_return, name='yookassa-return'),
    path('payments/fail/', fail, name='payment-fail'),
    path('download/<str:token>/', download, name='download'),
    path('robots.txt', views.robots, name='robots'), path('sitemap.xml', views.sitemap, name='sitemap'),
]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
