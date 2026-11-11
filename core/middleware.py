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
