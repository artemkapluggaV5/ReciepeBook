"""Run on the VPS: python3 deploy/configure_mail.py. Never prints the password."""
import getpass
import os
from pathlib import Path

path = Path(__file__).resolve().parents[1] / '.env'
if not path.is_file():
    raise SystemExit('Create .env before configuring email.')
password = getpass.getpass('Mail.ru app password (hidden): ').strip()
if not password or any(c in password for c in "\r\n\x00'\""):
    raise SystemExit('Password empty or contains unsupported quote/newline characters. Nothing changed.')
updates = {
    'EMAIL_BACKEND': 'django.core.mail.backends.smtp.EmailBackend',
    'EMAIL_HOST': 'smtp.mail.ru', 'EMAIL_PORT': '465',
    'EMAIL_USE_SSL': 'True', 'EMAIL_USE_TLS': 'False',
    'EMAIL_HOST_USER': 'marishkinirecepti@mail.ru',
    'EMAIL_HOST_PASSWORD': "'" + password + "'",
    'DEFAULT_FROM_EMAIL': 'Маришкины рецепты <marishkinirecepti@mail.ru>',
    'CONTACT_EMAIL': 'marishkinirecepti@mail.ru',
}
lines = []
for line in path.read_text(encoding='utf-8').splitlines():
    key = line.split('=', 1)[0].strip()
    if not line.lstrip().startswith('#') and key in updates:
        continue
    lines.append(line)
lines.extend(f'{key}={value}' for key, value in updates.items())
temp = path.with_name('.env.mail-tmp')
fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w', encoding='utf-8') as stream:
    stream.write('\n'.join(lines) + '\n')
temp.replace(path)
path.chmod(0o600)
print('SMTP saved securely. Recreate web/delivery containers to apply. No email sent; sales unchanged.')
