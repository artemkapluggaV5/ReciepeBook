import json
from io import BytesIO
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

from django.core.mail import EmailMultiAlternatives
from django.test import SimpleTestCase, override_settings

from delivery.backends import NoRedirect, production_email_ready


@override_settings(EMAIL_BACKEND='delivery.backends.UnisenderEmailBackend',
                   UNISENDER_API_KEY='test-only-not-a-credential',
                   UNISENDER_API_URL='https://go2.unisender.ru/ru/transactional/api/v1',
                   DEFAULT_FROM_EMAIL='Маришкины рецепты <book@example.test>',
                   SITE_URL='https://example.test', EMAIL_TIMEOUT=10)
class UnisenderTests(SimpleTestCase):
    def message(self):
        message = EmailMultiAlternatives('Ваш сборник', 'Личная ссылка на PDF',
                                        to=['buyer@example.test'], reply_to=['support@example.test'],
                                        headers={'Message-ID': '<stable-order@example.test>'})
        message.attach_alternative('<p>Личная ссылка на PDF</p>', 'text/html')
        return message

    def response(self, data):
        response = MagicMock()
        response.__enter__.return_value = response
        response.status = 200
        response.read.return_value = json.dumps(data).encode()
        return response

    @patch('delivery.backends.api_open')
    def test_success_preserves_email_parts_and_stable_retry_key(self, api):
        api.return_value = self.response({'status': 'success', 'job_id': 'job-test',
                                         'emails': ['buyer@example.test']})
        self.assertEqual(self.message().send(), 1)
        self.assertEqual(self.message().send(), 1)
        first, second = [call.args[0] for call in api.call_args_list]
        payload = json.loads(first.data)['message']
        self.assertEqual(first.full_url, 'https://go2.unisender.ru/ru/transactional/api/v1/email/send.json')
        self.assertEqual(first.get_header('X-api-key'), 'test-only-not-a-credential')
        self.assertNotIn('api_key', json.loads(first.data))
        self.assertEqual(payload['from_email'], 'book@example.test')
        self.assertEqual(payload['reply_to'], 'support@example.test')
        self.assertEqual(payload['body']['plaintext'], 'Личная ссылка на PDF')
        self.assertIn('<p>', payload['body']['html'])
        self.assertEqual(payload['idempotence_key'], json.loads(second.data)['message']['idempotence_key'])
        self.assertEqual(api.call_args.kwargs['timeout'], 10)

    @patch('delivery.backends.api_open')
    def test_recipient_rejection_or_false_success_is_not_counted(self, api):
        for result in [
            {'status': 'success', 'job_id': 'job-test', 'failed_emails': {'buyer@example.test': 'blocked'}},
            {'status': 'success', 'job_id': 'job-test', 'emails': []},
            {'status': 'success'}, {'status': 'error', 'code': 204}, [],
        ]:
            with self.subTest(result=result):
                api.return_value = self.response(result)
                with self.assertRaisesMessage(RuntimeError, 'did not accept'):
                    self.message().send()

    @patch('delivery.backends.api_open')
    def test_network_and_http_errors_do_not_expose_response_or_key(self, api):
        for failure in [URLError('private-server-data'),
                        HTTPError('https://go2.unisender.ru', 401, 'private-data', {}, BytesIO(b'private-data'))]:
            with self.subTest(failure=type(failure).__name__):
                api.side_effect = failure
                with self.assertRaises(RuntimeError) as error:
                    self.message().send()
                self.assertNotIn('private', str(error.exception))
                self.assertNotIn('test-only', str(error.exception))
        api.side_effect = TimeoutError()
        self.assertEqual(self.message().send(fail_silently=True), 0)

    @patch('delivery.backends.api_open')
    def test_invalid_json_is_failure(self, api):
        api.return_value = self.response({})
        api.return_value.read.return_value = b'not JSON'
        with self.assertRaisesMessage(RuntimeError, 'response error'):
            self.message().send()

    @patch('delivery.backends.api_open')
    def test_missing_key_or_untrusted_endpoint_never_contacts_network(self, api):
        for values in [{'UNISENDER_API_KEY': ''}, {'UNISENDER_API_URL': 'https://example.test'}]:
            with self.subTest(values=values), override_settings(**values):
                self.assertFalse(production_email_ready())
                with self.assertRaisesMessage(RuntimeError, 'configuration'):
                    self.message().send()
        api.assert_not_called()

    def test_production_readiness_requires_verified_sender_domain_configuration(self):
        self.assertTrue(production_email_ready())
        with override_settings(DEFAULT_FROM_EMAIL='test@mail.ru'):
            self.assertFalse(production_email_ready())
        # Redirects are not followed with the credential header.
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, '', {}, 'https://example.test'))

    @patch('delivery.backends.api_open')
    def test_no_pdf_attachments_or_multiple_recipients_are_silently_dropped(self, api):
        message = self.message()
        message.attach('test.pdf', b'%PDF', 'application/pdf')
        with self.assertRaises(ValueError):
            message.send()
        message = self.message()
        message.to.append('other@example.test')
        with self.assertRaises(ValueError):
            message.send()
        api.assert_not_called()
