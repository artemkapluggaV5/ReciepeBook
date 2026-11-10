from django.test import TestCase, override_settings
from products.models import Product, Review


class CozyPresentationTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(title='Зимняя книга', description='Описание', price='890.00')

    def test_only_approved_reviews_are_public_and_text_is_escaped(self):
        Review.objects.create(product=self.product, author='Автор', text='<script>private</script>')
        response = self.client.get('/')
        self.assertNotContains(response, 'private')
        self.assertContains(response, 'Не отзыв покупателя.')
        Review.objects.create(product=self.product, author='Читатель', text='<b>Спасибо!</b>', published=True)
        response = self.client.get('/')
        self.assertContains(response, '&lt;b&gt;Спасибо!&lt;/b&gt;')
        self.assertNotContains(response, 'Не отзыв покупателя.')

    @override_settings(TELEGRAM_USERNAME='cookbook_support')
    def test_telegram_uses_configured_username(self):
        self.assertContains(self.client.get('/'), 'href="https://t.me/cookbook_support"')

    @override_settings(TELEGRAM_USERNAME='')
    def test_missing_telegram_does_not_link_to_unrelated_account(self):
        response = self.client.get('/')
        self.assertContains(response, 'Ссылка на наш Telegram скоро появится здесь.')
        self.assertNotContains(response, 'href="https://t.me/')
