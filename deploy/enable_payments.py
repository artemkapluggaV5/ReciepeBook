"""Enable the owner's checkout switch; never invent keys or legal/fiscal readiness."""
import argparse
import os
from pathlib import Path
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument('--mode', choices=['live', 'test'], required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parent.parent
path = root / '.env'
if not path.is_file():
    raise SystemExit('Missing .env; run inside the existing server project.')
lines = path.read_text(encoding='utf-8').splitlines()
values = {}
for line in lines:
    if line.strip() and not line.lstrip().startswith('#') and '=' in line:
        key, value = line.split('=', 1)
        values[key.strip()] = value.strip().strip(chr(34) + chr(39))
required = ['YOOKASSA_SHOP_ID', 'YOOKASSA_SECRET_KEY']
missing = [key for key in required if not values.get(key) or values[key].startswith('[')]
if missing:
    raise SystemExit('Fill these settings locally in .env first (do not paste secrets in chat): ' + ', '.join(missing))
if values['YOOKASSA_SECRET_KEY'].startswith('test_') != (args.mode == 'test'):
    raise SystemExit('Key type does not match requested mode; file unchanged.')
updates = {'SALES_ENABLED': 'True', 'YOOKASSA_TEST_MODE': str(args.mode == 'test')}
output = []
seen = set()
for line in lines:
    key = line.split('=', 1)[0].strip()
    if not line.lstrip().startswith('#') and key in updates:
        if key not in seen:
            output.append(key + '=' + updates[key])
            seen.add(key)
    else:
        output.append(line)
output.extend(key + '=' + value for key, value in updates.items() if key not in seen)
fd, temporary = tempfile.mkstemp(prefix='.env.enable-', suffix='-tmp', dir=root)
try:
    with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
        stream.write('\n'.join(output) + '\n')
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)
finally:
    if Path(temporary).exists():
        Path(temporary).unlink()
print('Payment mode saved: ' + args.mode + '. Recreate web container to apply. No charge made.')
