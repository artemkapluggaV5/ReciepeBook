"""Private interactive setup; no keys in arguments, output, history or git."""
import argparse
from getpass import getpass
import os
from pathlib import Path
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument('--shop-id', default='1527129')
args = parser.parse_args()
if not args.shop_id.isdigit():
    raise SystemExit('Shop ID must contain digits.')
root = Path(__file__).resolve().parent.parent
path = root / '.env'
if not path.is_file():
    raise SystemExit('Configure the server .env first; existing database/secret settings must be retained.')
key = getpass('YooKassa TEST secret key (hidden input): ').strip()
if not key.startswith('test_') or any(c.isspace() for c in key):
    raise SystemExit('Expected a test_ key, file unchanged.')
updates = {'YOOKASSA_SHOP_ID':args.shop_id, 'YOOKASSA_SECRET_KEY':key,
           'YOOKASSA_TEST_MODE':'True', 'SALES_ENABLED':'True'}
output = []
for line in path.read_text(encoding='utf-8').splitlines():
    name = line.split('=', 1)[0].strip()
    if name.startswith('ROBOKASSA_') and not line.lstrip().startswith('#'):
        continue
    if name in updates and not line.lstrip().startswith('#'):
        continue
    output.append(line)
output.extend(name + '=' + value for name, value in updates.items())
fd, temporary = tempfile.mkstemp(prefix='.env.yookassa-', suffix='-tmp', dir=root)
try:
    with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
        stream.write('\n'.join(output) + '\n')
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)
finally:
    if Path(temporary).exists():
        Path(temporary).unlink()
print('YooKassa test checkout enabled in .env. Recreate web container. Key not printed.')
