from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from django.conf import settings
from django.test import SimpleTestCase


class PaymentActivationTests(SimpleTestCase):
    def run_activation(self, content, mode):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'deploy').mkdir()
            script = root / 'deploy' / 'enable_payments.py'
            shutil.copyfile(settings.BASE_DIR / 'deploy' / script.name, script)
            path = root / '.env'
            path.write_text(content, encoding='utf-8')
            result = subprocess.run(
                [sys.executable, str(script), '--mode', mode],
                capture_output=True, text=True, timeout=10,
            )
            return result, path.read_text(encoding='utf-8')

    def test_live_activation_preserves_credentials_and_review_flags(self):
        content = ('ROBOKASSA_MERCHANT_LOGIN=merchant\n'
                   'ROBOKASSA_PASSWORD1=private-one\nROBOKASSA_PASSWORD2=private-two\n'
                   'SALES_ENABLED=False\nSALES_ENABLED=False\nROBOKASSA_TEST_MODE=True\n'
                   'LEGAL_READY=False\nFISCALIZATION_READY=False\n')
        result, saved = self.run_activation(content, 'live')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(saved.count('SALES_ENABLED=True'), 1)
        self.assertIn('ROBOKASSA_TEST_MODE=False', saved)
        self.assertIn('LEGAL_READY=False\nFISCALIZATION_READY=False', saved)
        self.assertIn('ROBOKASSA_PASSWORD1=private-one', saved)
        self.assertNotIn('private-one', result.stdout + result.stderr)
        self.assertNotIn('private-two', result.stdout + result.stderr)

    def test_missing_live_passwords_leave_file_unchanged(self):
        content = ('ROBOKASSA_MERCHANT_LOGIN=merchant\n'
                   'ROBOKASSA_TEST_PASSWORD1=test-one\nROBOKASSA_TEST_PASSWORD2=test-two\n'
                   'SALES_ENABLED=False\n')
        result, saved = self.run_activation(content, 'live')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(saved, content)
        self.assertIn('ROBOKASSA_PASSWORD1', result.stderr)

    def test_test_mode_uses_separate_passwords(self):
        content = ('ROBOKASSA_MERCHANT_LOGIN=merchant\n'
                   'ROBOKASSA_TEST_PASSWORD1=test-one\nROBOKASSA_TEST_PASSWORD2=test-two\n')
        result, saved = self.run_activation(content, 'test')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('SALES_ENABLED=True', saved)
        self.assertIn('ROBOKASSA_TEST_MODE=True', saved)
