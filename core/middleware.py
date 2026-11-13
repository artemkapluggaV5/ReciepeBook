from django.conf import settings
from django.http import HttpResponseRedirect


class CanonicalHostMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        host = request.get_host().split(':', 1)[0].lower().rstrip('.')
        if not settings.CANONICAL_HOST or host not in settings.CANONICAL_REDIRECT_HOSTS or request.path == '/health/':
            return self.get_response(request)

        if request.method not in {'GET', 'HEAD'}:
            if request.path == '/checkout/':
                # An old, already-open form belongs to the apex host's cookie.
                # Start a fresh form on www before creating or charging an order.
                response = HttpResponseRedirect(settings.SITE_URL + '/#purchase')
                response.status_code = 303
            else:
                # Payment callbacks must be processed at their registered URL.
                return self.get_response(request)
        elif request.path.startswith(('/order/', '/download/', '/payments/')) and request.session.get('orders'):
            # Preserve host-only ownership for purchases made before www became
            # canonical. No session IDs or paid capabilities travel in URLs.
            return self.get_response(request)
        else:
            response = HttpResponseRedirect(settings.SITE_URL + request.get_full_path())
            response.status_code = 308
        response['Cache-Control'] = 'private, no-store'
        return response


class SecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
    def __call__(self, request):
        if request.path == '/admin/login/' and request.method == 'POST':
            from orders.rate_limit import limited
            from django.http import HttpResponse
            if limited(request, 'admin-login', limit=10, seconds=600):
                return HttpResponse('Слишком много попыток. Повторите позже.', status=429)
        response = self.get_response(request)
        response['Content-Security-Policy'] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
            "font-src 'self'; connect-src 'self'; form-action 'self' https://yoomoney.ru https://yookassa.ru; frame-ancestors 'none'; base-uri 'self'; object-src 'none'"
        )
        response['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
        if request.path.startswith(('/order/', '/download/', '/checkout/', '/payments/', '/admin/')):
            response['Cache-Control'] = 'private, no-store'
            response['X-Robots-Tag'] = 'noindex, nofollow'
        if request.path.startswith('/download/'):
            response['Referrer-Policy'] = 'no-referrer'
        return response
