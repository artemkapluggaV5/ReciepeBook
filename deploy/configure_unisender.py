"""Run on VPS: python3 deploy/configure_unisender.py. Key input is hidden."""
import getpass
import os
from pathlib import Path

path = Path(__file__).resolve().parents[1] / '.env'
if not path.is_file():
    raise SystemExit('Create .env first.')
key = getpass.getpass('NEW Unisender Go API key (hidden): ').strip()
if not key or not key.isascii() or not all(c.isalnum() or c in '-_' for c in key):
    raise SystemExit('Invalid key. Nothing changed.')
updates = {
    'EMAIL_BACKEND': 'delivery.backends.UnisenderEmailBackend',
    'UNISENDER_API_KEY': key,
    'UNISENDER_API_URL': 'https://go2.unisender.ru/ru/transactional/api/v1',
    'DEFAULT_FROM_EMAIL': 'Маришкины рецепты <book@marishkinirecepti.ru>',
    'CONTACT_EMAIL': 'marishkinirecepti@mail.ru',
}
lines = [line for line in path.read_text(encoding='utf-8').splitlines()
         if line.lstrip().startswith('#') or line.split('=', 1)[0].strip() not in updates]
lines.extend(f'{name}={value}' for name, value in updates.items())
temp = path.with_name('.env.unisender-tmp')
fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w', encoding='utf-8') as stream:
    stream.write('\n'.join(lines) + '\n')
temp.replace(path)
path.chmod(0o600)
print('Unisender saved. Recreate web/delivery containers to apply. No email sent; sales unchanged.')
