#!/usr/bin/env python3
"""
Fetch symbol list from Supabase and update local symbols.json.
Run this to keep the local file in sync with the Supabase symbols table.
"""
import os
import json

from supabase import create_client

SUPABASE_URL = os.environ.get('SUPABASE_URL', 'https://pggshikvapdnukpzoznk.supabase.co')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY', 'sb_publishable_BgGQTZmkECmAwRAOM6Bmig_uTafg82R')

def main():
    client = create_client(SUPABASE_URL, SUPABASE_KEY)
    response = client.table('symbols').select('symbol').execute()
    if not response.data:
        print('No symbols in Supabase.')
        return
    symbols = sorted([row['symbol'] for row in response.data])
    path = os.path.join(os.path.dirname(__file__), 'symbols.json')
    with open(path, 'w') as f:
        json.dump(symbols, f, indent=0)
    print(f'Updated {path} with {len(symbols)} symbols from Supabase.')

if __name__ == '__main__':
    main()
