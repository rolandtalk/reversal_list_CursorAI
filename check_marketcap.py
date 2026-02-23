import yfinance as yf

symbols = ['SNDK', 'LITE', 'WDC', 'MU', 'AG', 'SATS', 'BE', 'HL', 'TTMI', 'MKSI', 
           'ASX', 'RVMD', 'LRCX', 'ATI', 'TSEM', 'ROIV', 'RGC', 'WBD', 'AU', 'MT',
           'VRT', 'CDE', 'PAAS', 'EQX', 'TPL', 'AXIA', 'FTAI', 'UI', 'EXAS', 'MTSI',
           'FN', 'ONTO', 'FTI', 'XPO', 'AA', 'CAT', 'FDX', 'NXT', 'NOK', 'AMKR',
           'TECK', 'AGI', 'TEVA', 'B', 'GFI', 'LUV', 'AEM', 'MTZ', 'TPR']

under_1b = []
all_caps = []

for sym in symbols:
    try:
        ticker = yf.Ticker(sym)
        info = ticker.info
        cap = info.get('marketCap', 0)
        if cap:
            cap_b = cap / 1e9
            all_caps.append((sym, cap_b))
            if cap_b < 1:
                under_1b.append((sym, cap_b))
        else:
            all_caps.append((sym, None))
    except Exception as e:
        all_caps.append((sym, None))

print('=== Market Cap < 1 Billion USD ===')
if under_1b:
    for sym, cap in under_1b:
        print(f'{sym}: ${cap:.2f}B')
else:
    print('None found')

print()
print('=== All Stocks Market Cap (sorted by size) ===')
for sym, cap in sorted(all_caps, key=lambda x: x[1] if x[1] else 0):
    if cap:
        print(f'{sym}: ${cap:.2f}B')
    else:
        print(f'{sym}: N/A')
