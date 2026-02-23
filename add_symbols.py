import requests

symbols = ['SNDK', 'LITE', 'WDC', 'MU', 'AG', 'SATS', 'BE', 'HL', 'TTMI', 'MKSI', 
           'ASX', 'RVMD', 'LRCX', 'ATI', 'TSEM', 'ROIV', 'RGC', 'WBD', 'AU', 'MT',
           'VRT', 'CDE', 'PAAS', 'EQX', 'TPL', 'AXIA', 'FTAI', 'UI', 'EXAS', 'MTSI',
           'FN', 'ONTO', 'FTI', 'XPO', 'AA', 'CAT', 'FDX', 'NXT', 'NOK', 'AMKR',
           'TECK', 'AGI', 'TEVA', 'B', 'GFI', 'LUV', 'AEM', 'MTZ', 'TPR']

BASE_URL = 'https://reversal.up.railway.app'

success = []
failed = []

for sym in symbols:
    try:
        resp = requests.post(f'{BASE_URL}/api/symbols/add', json={'symbol': sym})
        if resp.status_code == 200:
            success.append(sym)
            print(f'✓ {sym} added')
        else:
            error = resp.json().get('error', 'Unknown error')
            failed.append((sym, error))
            print(f'✗ {sym}: {error}')
    except Exception as e:
        failed.append((sym, str(e)))
        print(f'✗ {sym}: {e}')

print(f'\n=== Summary ===')
print(f'Success: {len(success)}')
print(f'Failed: {len(failed)}')
if failed:
    print('\nFailed symbols:')
    for sym, err in failed:
        print(f'  {sym}: {err}')
