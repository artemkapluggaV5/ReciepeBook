"""Optional real Chrome regression: python tests/browser_checkout.py (pip install playwright)."""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.test_settings')
import django
django.setup()
from django.http import HttpResponse
from django.test import RequestFactory
from core.middleware import SecurityHeadersMiddleware
from playwright.sync_api import sync_playwright

root=Path(__file__).resolve().parents[1]
script=(root/'static/js/site.js').read_text(encoding='utf-8')
policy=SecurityHeadersMiddleware(lambda request: HttpResponse(''))(RequestFactory().get('/')).headers['Content-Security-Policy']
html='<!doctype html><html lang="ru"><body><form id="purchase-form" action="/checkout/" method="post"><input name="request_key" value="same-key"><button type="submit" data-loading="Loading">Buy</button><p class="form-status" aria-live="polite"></p></form><script src="/site.js" defer></script></body></html>'

with sync_playwright() as p:
    browser=p.chromium.launch(channel='chrome',headless=True)
    for blocked in [True,False]:
        page=browser.new_page()
        headers={'Content-Security-Policy':"form-action 'self'" if blocked else policy}
        def handler(route):
            url=route.request.url
            if url=='http://shop.test/':
                route.fulfill(status=200,content_type='text/html',headers=headers,body=html)
            elif url=='http://shop.test/site.js':
                route.fulfill(status=200,content_type='application/javascript',body=script)
            elif url=='http://shop.test/checkout/':
                route.fulfill(status=302,headers={'Location':'https://yoomoney.ru/checkout/test'})
            else:
                route.fulfill(status=200,content_type='text/html',body='<h1>Payment page</h1>')
        violations=[]
        page.on('console', lambda message: violations.append(message.text) if 'form-action' in message.text else None)
        page.route('**/*',handler)
        page.goto('http://shop.test/')
        page.locator('button').click()
        if blocked:
            page.wait_for_function("!document.querySelector('button').disabled")
            assert page.url=='http://shop.test/'
            assert page.locator('.form-status').inner_text()
            print('Chrome: reproduced old CSP block; button recovered.')
        else:
            page.wait_for_url('https://yoomoney.ru/checkout/test')
            assert not violations, violations
            print('Chrome: fixed policy permits POST -> 302 navigation to payment host without CSP violation.')
        page.close()
    page=browser.new_page()
    page.route('**/*',handler)
    page.clock.install()
    page.goto('http://shop.test/')
    page.evaluate("document.querySelector('form').dispatchEvent(new Event('submit', {cancelable:true}))")
    assert page.locator('button').is_disabled()
    page.clock.run_for(20001)
    assert page.locator('button').is_enabled()
    assert page.locator('form').get_attribute('aria-busy') is None
    print('Chrome: interrupted-navigation timeout restores retry button.')
    browser.close()
