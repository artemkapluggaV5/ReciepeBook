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

    def test_enable_test_mode_without_disclosing_key(self):
        result, saved = self.run_activation('YOOKASSA_SHOP_ID=123\nYOOKASSA_SECRET_KEY=test_private\nSALES_ENABLED=False\n', 'test')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('SALES_ENABLED=True', saved)
        self.assertIn('YOOKASSA_TEST_MODE=True', saved)
        self.assertNotIn('test_private', result.stdout + result.stderr)

    def test_missing_key_leaves_file_unchanged(self):
        content = 'YOOKASSA_SHOP_ID=123\n'
        result, saved = self.run_activation(content, 'test')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(content, saved)

    def test_test_key_cannot_enable_live_mode(self):
        content = 'YOOKASSA_SHOP_ID=123\nYOOKASSA_SECRET_KEY=test_private\n'
        result, saved = self.run_activation(content, 'live')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(content, saved)
