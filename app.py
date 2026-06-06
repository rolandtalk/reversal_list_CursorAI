"""
Stock Reversal Point Analysis Web App
Based on MA3 reversal point detection algorithm
"""

from flask import Flask, render_template, jsonify, request, redirect
from flask_cors import CORS
import yfinance as yf
import pandas as pd
from datetime import datetime
import json
import os
import time
import urllib.parse
import urllib.request
import warnings
warnings.filterwarnings('ignore')

from google.oauth2 import service_account
from googleapiclient.discovery import build

app = Flask(__name__, static_folder='static')
CORS(app)

# Simple cache
DATA_CACHE = {'data': None, 'timestamp': 0}
CACHE_TTL = 300  # 5 minutes

# Google Sheets configuration
GOOGLE_SHEET_ID = os.environ.get('GOOGLE_SHEET_ID', '1Rq-qt_rg6JiGX63xOcr2pvR-HWoILhL2fqeOrrO37Og')
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON', '').strip()
GOOGLE_SERVICE_ACCOUNT_FILE = os.environ.get('GOOGLE_SERVICE_ACCOUNT_FILE', '').strip()
GOOGLE_APPS_SCRIPT_WEB_APP_URL = os.environ.get('GOOGLE_APPS_SCRIPT_WEB_APP_URL', '').strip()
GOOGLE_APPS_SCRIPT_SHARED_SECRET = os.environ.get('GOOGLE_APPS_SCRIPT_SHARED_SECRET', '').strip()
GOOGLE_SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

SYMBOLS_SHEET = 'symbols'
SIM_POSITIONS_SHEET = 'sim_positions'
SETTINGS_SHEET = 'settings'
AUDIT_LOG_SHEET = 'audit_log'
LOCAL_SYMBOL_OVERRIDES_PATH = os.path.join(app.root_path, 'symbols_local_overrides.json')

_SHEETS_SERVICE = None

# This deployment's public URL (dupe repo — avoid confusion with production)
APP_BASE_URL = os.environ.get('APP_BASE_URL', 'https://reversal.up.railway.app')


@app.context_processor
def inject_base_url():
    return {'base_url': APP_BASE_URL}


def _today_iso():
    return datetime.now().strftime('%Y-%m-%d')


def _now_iso():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _to_bool(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {'1', 'true', 'yes', 'y'}


def _build_sheets_service():
    if GOOGLE_SERVICE_ACCOUNT_JSON:
        credentials = service_account.Credentials.from_service_account_info(
            json.loads(GOOGLE_SERVICE_ACCOUNT_JSON),
            scopes=GOOGLE_SCOPES,
        )
        return build('sheets', 'v4', credentials=credentials, cache_discovery=False)

    if GOOGLE_SERVICE_ACCOUNT_FILE:
        credentials = service_account.Credentials.from_service_account_file(
            GOOGLE_SERVICE_ACCOUNT_FILE,
            scopes=GOOGLE_SCOPES,
        )
        return build('sheets', 'v4', credentials=credentials, cache_discovery=False)

    return None


def get_sheets_service():
    global _SHEETS_SERVICE

    if _SHEETS_SERVICE is None:
        _SHEETS_SERVICE = _build_sheets_service()

    return _SHEETS_SERVICE


def has_sheet_write_access():
    return get_sheets_service() is not None


def has_apps_script_write_access():
    return bool(GOOGLE_APPS_SCRIPT_WEB_APP_URL)


def has_shared_sheet_write_access():
    return has_sheet_write_access() or has_apps_script_write_access()


def get_write_mode():
    if has_sheet_write_access():
        return 'service_account'
    if has_apps_script_write_access():
        return 'apps_script'
    return 'local_overrides'


def write_access_error_message():
    return 'Shared Google Sheet writes are not configured. Local add/remove still works in this runtime. For universal shared writes, set GOOGLE_APPS_SCRIPT_WEB_APP_URL.'


def _column_letter(index):
    result = ''
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _normalize_row(values, width):
    row = list(values[:width])
    if len(row) < width:
        row.extend([''] * (width - len(row)))
    return row


def _fetch_sheet_rows_api(sheet_name):
    service = get_sheets_service()
    if service is None:
        return None

    response = service.spreadsheets().values().get(
        spreadsheetId=GOOGLE_SHEET_ID,
        range=f'{sheet_name}!A:Z',
    ).execute()
    return response.get('values', [])


def _open_url_with_retries(url, attempts=3, delay=0.5):
    last_error = None
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(url) as response:
                return response.read().decode('utf-8')
        except Exception as e:
            last_error = e
            if attempt == attempts - 1:
                raise
            time.sleep(delay * (attempt + 1))
    raise last_error


def _parse_gviz_response(text):
    prefix = 'google.visualization.Query.setResponse('
    start = text.find(prefix)
    end = text.rfind(');')
    if start == -1 or end == -1:
        raise ValueError('Unexpected Google visualization payload')
    payload = text[start + len(prefix):end]
    return json.loads(payload)


def _fetch_sheet_rows_public(sheet_name):
    params = urllib.parse.urlencode({
        'sheet': sheet_name,
        'tqx': 'out:json',
    })
    url = f'https://docs.google.com/spreadsheets/d/{GOOGLE_SHEET_ID}/gviz/tq?{params}'
    payload = _open_url_with_retries(url)
    table = _parse_gviz_response(payload).get('table', {})
    headers = [col.get('label') or col.get('id') or '' for col in table.get('cols', [])]
    rows = [headers]
    for row in table.get('rows', []):
        values = []
        for cell in row.get('c', []):
            values.append('' if cell is None else cell.get('v', ''))
        rows.append(values)
    return rows


def read_sheet_records(sheet_name):
    rows = _fetch_sheet_rows_api(sheet_name)
    if rows is None:
        rows = _fetch_sheet_rows_public(sheet_name)

    if not rows:
        return []

    headers = [str(value).strip() for value in rows[0]]
    width = len(headers)
    records = []
    for row_number, row_values in enumerate(rows[1:], start=2):
        row = _normalize_row(row_values, width)
        if not any(str(value).strip() for value in row):
            continue

        record = {headers[index]: row[index] for index in range(width)}
        record['_row_number'] = row_number
        records.append(record)

    return records


def _update_sheet_row(sheet_name, row_number, values):
    service = get_sheets_service()
    if service is None:
        raise RuntimeError('Google Sheets write access is not configured. Set GOOGLE_SERVICE_ACCOUNT_JSON or GOOGLE_SERVICE_ACCOUNT_FILE.')

    end_column = _column_letter(len(values))
    service.spreadsheets().values().update(
        spreadsheetId=GOOGLE_SHEET_ID,
        range=f'{sheet_name}!A{row_number}:{end_column}{row_number}',
        valueInputOption='USER_ENTERED',
        body={'values': [values]},
    ).execute()


def _append_sheet_row(sheet_name, values):
    service = get_sheets_service()
    if service is None:
        raise RuntimeError('Google Sheets write access is not configured. Set GOOGLE_SERVICE_ACCOUNT_JSON or GOOGLE_SERVICE_ACCOUNT_FILE.')

    service.spreadsheets().values().append(
        spreadsheetId=GOOGLE_SHEET_ID,
        range=f'{sheet_name}!A1',
        valueInputOption='USER_ENTERED',
        insertDataOption='INSERT_ROWS',
        body={'values': [values]},
    ).execute()


def _log_audit(action, table_name, symbol='', old_value='', new_value='', notes=''):
    if not has_sheet_write_access():
        return

    try:
        _append_sheet_row(
            AUDIT_LOG_SHEET,
            [_now_iso(), action, table_name, symbol, old_value, new_value, 'app', notes],
        )
    except Exception as e:
        print(f'Error writing audit log: {e}')


def _post_apps_script(action, payload):
    if not has_apps_script_write_access():
        return False, 'Apps Script write endpoint is not configured.'

    body = {
        'action': action,
        'sheet_id': GOOGLE_SHEET_ID,
        'payload': payload,
    }
    if GOOGLE_APPS_SCRIPT_SHARED_SECRET:
        body['secret'] = GOOGLE_APPS_SCRIPT_SHARED_SECRET

    request_data = json.dumps(body).encode('utf-8')
    req = urllib.request.Request(
        GOOGLE_APPS_SCRIPT_WEB_APP_URL,
        data=request_data,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            text = response.read().decode('utf-8')
        data = json.loads(text) if text else {}
    except Exception as e:
        return False, str(e)

    if data.get('success'):
        return True, None
    return False, data.get('error') or 'Apps Script write failed'


def _read_local_symbol_overrides():
    if not os.path.exists(LOCAL_SYMBOL_OVERRIDES_PATH):
        return {'added': [], 'removed': []}

    try:
        with open(LOCAL_SYMBOL_OVERRIDES_PATH, 'r', encoding='utf-8') as file:
            data = json.load(file)
    except Exception as e:
        print(f'Error reading local symbol overrides: {e}')
        return {'added': [], 'removed': []}

    added = sorted({str(symbol).upper().strip() for symbol in data.get('added', []) if str(symbol).strip()})
    removed = sorted({str(symbol).upper().strip() for symbol in data.get('removed', []) if str(symbol).strip()})
    return {'added': added, 'removed': removed}


def _write_local_symbol_overrides(overrides):
    normalized = {
        'added': sorted({str(symbol).upper().strip() for symbol in overrides.get('added', []) if str(symbol).strip()}),
        'removed': sorted({str(symbol).upper().strip() for symbol in overrides.get('removed', []) if str(symbol).strip()}),
    }
    with open(LOCAL_SYMBOL_OVERRIDES_PATH, 'w', encoding='utf-8') as file:
        json.dump(normalized, file, indent=2)


def _apply_local_symbol_overrides(symbols):
    overrides = _read_local_symbol_overrides()
    merged = set(symbols)
    merged.update(overrides['added'])
    merged.difference_update(overrides['removed'])
    return sorted(merged)


# Default symbol list (used for initial setup)
DEFAULT_SYMBOLS = [
    "AAPL", "ABBV", "ACHR", "ADBE", "ADSK", "AFRM", "AIG", "ALB", "AMAT", "AMD", "AMZN",
    "ANET", "APP", "ARKG", "ARKK", "ARKX", "ASML", "ASTS", "AVAV", "AVGO", "BA", "BABA", "BAX",
    "BNTX", "CCL", "CEG", "COF", "COHR", "COIN", "COST", "CQQQ", "CRM",
    "CRSP", "CRWD", "CSCO", "CVNA", "CVS", "DE", "DECK", "DELL", "DIS", "DOCU",
    "EMB", "ENPH", "ERO", "EWZ", "EZU", "FCX", "FLY", "FNGS", "GBTC", "GDRX",
    "GDX", "GE", "GLD", "GLW", "GOOG", "HIMS", "HOOD", "HUBS", "HWM", "HYG",
    "IBM", "INDA", "INMD", "INTU", "IONQ", "ISRG", "JD", "JETS", "JPM",
    "LEMB", "LHX", "LLY", "LQD", "MCHI", "MDT", "META", "MGM", "MP",
    "MRNA", "MSFT", "MSTR", "NEE", "NET", "NEU", "NFLX", "NOW", "NUGT", "NVDA",
    "PFE", "PINS", "PL", "PLTR", "PYPL", "QS", "RBLX", "RKLB", "ROBO", "RXRX",
    "SAP", "SE", "SHOP", "SHY", "SMCI", "SNAP", "SNOW", "SCCO", "SO", "SOFI", "SOUN",
    "SOXX", "SPOT", "SRAD", "STX", "TDOC", "TEAM", "TEM", "TER", "TJX", "TLRY", "TLT", "TMF",
    "TMO", "TMV", "TSLA", "TTD", "TWST", "TXN", "U", "UNH", "UPS", "URNM", "V",
    "WYNN", "XLE", "XLF", "XME", "XOP", "XPEV", "ZM"
]

def load_symbols():
    """Load active symbols from Google Sheets."""
    try:
        records = read_sheet_records(SYMBOLS_SHEET)
        symbols = []
        for record in records:
            symbol = str(record.get('symbol', '')).upper().strip()
            if symbol and _to_bool(record.get('active', True)):
                symbols.append(symbol)

        if symbols:
            return _apply_local_symbol_overrides(symbols)

        if has_sheet_write_access():
            init_default_symbols()
            return _apply_local_symbol_overrides(DEFAULT_SYMBOLS.copy())

        print("Google Sheet symbols tab is empty; using local defaults")
        return _apply_local_symbol_overrides(DEFAULT_SYMBOLS.copy())
    except Exception as e:
        print(f"Error loading symbols from Google Sheets: {e}")
        return _apply_local_symbol_overrides(DEFAULT_SYMBOLS.copy())


def init_default_symbols():
    """Initialize the symbols sheet when it is empty."""
    try:
        today = _today_iso()
        for symbol in DEFAULT_SYMBOLS:
            _append_sheet_row(SYMBOLS_SHEET, [symbol, 'TRUE', today, ''])
        print("Initialized default symbols in Google Sheets")
    except Exception as e:
        print(f"Error initializing symbols: {e}")


def add_symbol_to_db(symbol):
    """Add or reactivate a symbol in Google Sheets."""
    if has_apps_script_write_access() and not has_sheet_write_access():
        return _post_apps_script('upsert_symbol', {'symbol': symbol})

    if not has_sheet_write_access():
        try:
            overrides = _read_local_symbol_overrides()
            added = set(overrides['added'])
            removed = set(overrides['removed'])
            added.add(symbol)
            removed.discard(symbol)
            _write_local_symbol_overrides({'added': sorted(added), 'removed': sorted(removed)})
            return True, None
        except Exception as e:
            print(f"Error adding local symbol override: {e}")
            return False, str(e)

    try:
        records = read_sheet_records(SYMBOLS_SHEET)
        today = _today_iso()

        for record in records:
            if str(record.get('symbol', '')).upper().strip() != symbol:
                continue

            updated = [
                symbol,
                'TRUE',
                record.get('added_at') or today,
                record.get('notes', ''),
            ]
            _update_sheet_row(SYMBOLS_SHEET, record['_row_number'], updated)
            _log_audit('upsert', SYMBOLS_SHEET, symbol, json.dumps(record, default=str), json.dumps(updated))
            return True, None

        new_row = [symbol, 'TRUE', today, '']
        _append_sheet_row(SYMBOLS_SHEET, new_row)
        _log_audit('insert', SYMBOLS_SHEET, symbol, '', json.dumps(new_row))
        return True, None
    except Exception as e:
        print(f"Error adding symbol: {e}")
        return False, str(e)


def remove_symbol_from_db(symbol):
    """Soft-delete a symbol in Google Sheets by marking it inactive."""
    if has_apps_script_write_access() and not has_sheet_write_access():
        return _post_apps_script('deactivate_symbol', {'symbol': symbol})

    if not has_sheet_write_access():
        try:
            overrides = _read_local_symbol_overrides()
            added = set(overrides['added'])
            removed = set(overrides['removed'])
            added.discard(symbol)
            removed.add(symbol)
            _write_local_symbol_overrides({'added': sorted(added), 'removed': sorted(removed)})
            return True, None
        except Exception as e:
            print(f"Error removing local symbol override: {e}")
            return False, str(e)

    try:
        records = read_sheet_records(SYMBOLS_SHEET)
        for record in records:
            if str(record.get('symbol', '')).upper().strip() != symbol:
                continue

            updated = [
                symbol,
                'FALSE',
                record.get('added_at', ''),
                record.get('notes', ''),
            ]
            _update_sheet_row(SYMBOLS_SHEET, record['_row_number'], updated)
            _log_audit('deactivate', SYMBOLS_SHEET, symbol, json.dumps(record, default=str), json.dumps(updated))
            return True, None

        return False, f'{symbol} not found'
    except Exception as e:
        print(f"Error removing symbol: {e}")
        return False, str(e)


def load_sim_positions_from_sheet():
    """Load active SIM holdings from Google Sheets."""
    try:
        records = read_sheet_records(SIM_POSITIONS_SHEET)
        positions = []
        for record in records:
            symbol = str(record.get('symbol', '')).upper().strip()
            if not symbol or not _to_bool(record.get('active', True)):
                continue

            positions.append({
                'symbol': symbol,
                'shares': float(record.get('shares') or 0),
                'cost': float(record.get('cost') or 0),
                'buy_date': str(record.get('buy_date') or ''),
                'active': True,
                'updated_at': str(record.get('updated_at') or ''),
            })

        positions.sort(key=lambda row: (row['buy_date'], row['symbol']))
        return positions
    except Exception as e:
        print(f"Error loading SIM positions: {e}")
        return []


def upsert_sim_position_in_sheet(symbol, shares, cost, buy_date):
    """Add or update a SIM holding row in Google Sheets."""
    if has_apps_script_write_access() and not has_sheet_write_access():
        return _post_apps_script('upsert_sim_position', {
            'symbol': symbol,
            'shares': shares,
            'cost': cost,
            'buy_date': buy_date,
        })

    try:
        records = read_sheet_records(SIM_POSITIONS_SHEET)
        updated_at = _today_iso()
        new_row = [symbol, shares, cost, buy_date, 'TRUE', updated_at]

        for record in records:
            if str(record.get('symbol', '')).upper().strip() != symbol:
                continue

            _update_sheet_row(SIM_POSITIONS_SHEET, record['_row_number'], new_row)
            _log_audit('upsert', SIM_POSITIONS_SHEET, symbol, json.dumps(record, default=str), json.dumps(new_row))
            return True, None

        _append_sheet_row(SIM_POSITIONS_SHEET, new_row)
        _log_audit('insert', SIM_POSITIONS_SHEET, symbol, '', json.dumps(new_row))
        return True, None
    except Exception as e:
        print(f"Error upserting SIM position: {e}")
        return False, str(e)


def delete_sim_position_from_sheet(symbol):
    """Soft-delete a SIM holding by marking it inactive."""
    if has_apps_script_write_access() and not has_sheet_write_access():
        return _post_apps_script('deactivate_sim_position', {'symbol': symbol})

    try:
        records = read_sheet_records(SIM_POSITIONS_SHEET)
        for record in records:
            if str(record.get('symbol', '')).upper().strip() != symbol:
                continue

            updated = [
                symbol,
                record.get('shares', ''),
                record.get('cost', ''),
                record.get('buy_date', ''),
                'FALSE',
                _today_iso(),
            ]
            _update_sheet_row(SIM_POSITIONS_SHEET, record['_row_number'], updated)
            _log_audit('deactivate', SIM_POSITIONS_SHEET, symbol, json.dumps(record, default=str), json.dumps(updated))
            return True, None

        return False, f'{symbol} not found'
    except Exception as e:
        print(f"Error deleting SIM position: {e}")
        return False, str(e)

def calculate_rsi(prices, period=14):
    """Calculate RSI (Relative Strength Index)"""
    delta = prices.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def _placeholder_result(sym):
    """Row when a symbol is in DB but Yahoo/reversal pipeline has no row yet."""
    return {
        'sym': sym,
        'dg': None,
        'gg': None,
        'rsi': None,
        'd1': None,
        'd3': None,
        'd5': None,
        'd20': None,
    }


def merge_missing_symbols(rows, symbols):
    """Ensure every configured symbol appears at least once (placeholders last)."""
    have = {r['sym'] for r in rows}
    out = list(rows)
    for sym in symbols:
        if sym not in have:
            out.append(_placeholder_result(sym))
    out.sort(key=lambda x: (x['dg'] is None, float(x['dg']) if x['dg'] is not None else 0.0))
    return out


def batch_calculate_all(symbols):
    """Batch download and calculate all symbols at once - MUCH faster"""
    try:
        # Batch download all symbols at once
        data = yf.download(symbols, period="60d", group_by='ticker', progress=False, threads=True)
        results = []
        
        for symbol in symbols:
            try:
                if len(symbols) == 1:
                    if isinstance(data.columns, pd.MultiIndex):
                        df = data[symbol].copy() if symbol in data.columns.get_level_values(0) else None
                    else:
                        df = data
                else:
                    df = data[symbol] if symbol in data.columns.get_level_values(0) else None
                
                if df is None or df.empty or len(df) < 20:
                    continue
                
                close = df['Close'].dropna()
                if len(close) < 20:
                    continue
                
                ma3 = close.rolling(3).mean()
                rsi = calculate_rsi(close, 14)
                
                work_df = pd.DataFrame({'Close': close, 'MA3': ma3}).dropna()
                if len(work_df) < 5:
                    continue
                
                # Find reversal points
                work_df['Below'] = work_df['Close'] < work_df['MA3']
                segments = []
                in_seg = False
                start = 0
                for i in range(len(work_df)):
                    if work_df['Below'].iloc[i] and not in_seg:
                        in_seg = True
                        start = i
                    elif not work_df['Below'].iloc[i] and in_seg:
                        in_seg = False
                        segments.append((start, i-1))
                if in_seg:
                    segments.append((start, len(work_df)-1))
                
                if not segments:
                    continue
                
                rev_points = [work_df.iloc[s:e+1]['Close'].idxmin() for s, e in segments]
                last_rev = rev_points[-1]
                last_rev_price = float(work_df.loc[last_rev, 'Close'])
                curr_price = float(work_df['Close'].iloc[-1])
                curr_date = work_df.index[-1]
                
                dg = (curr_date - last_rev).days
                gg = ((curr_price - last_rev_price) / last_rev_price) * 100
                
                def gain(d):
                    if len(work_df) > d:
                        return ((curr_price - float(work_df['Close'].iloc[-d-1])) / float(work_df['Close'].iloc[-d-1])) * 100
                    return 0.0
                
                results.append({
                    'sym': symbol,
                    'dg': dg,
                    'gg': round(gg, 2),
                    'rsi': round(float(rsi.iloc[-1]), 1) if not pd.isna(rsi.iloc[-1]) else None,
                    'd1': round(gain(1), 2),
                    'd3': round(gain(3), 2),
                    'd5': round(gain(5), 2),
                    'd20': round(gain(20), 2)
                })
            except Exception as e:
                continue
        
        return results
    except Exception as e:
        print(f"Batch download error: {e}")
        return []

def calculate_reversal_data(symbol):
    """Calculate reversal point data for a single symbol"""
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period="60d")
        
        if df.empty or len(df) < 20:
            return None
        
        close_prices = df['Close'].copy()
        
        # Calculate MA3
        ma3 = close_prices.rolling(window=3).mean()
        
        # Calculate RSI(14)
        rsi = calculate_rsi(close_prices, 14)
        current_rsi = float(rsi.iloc[-1]) if not pd.isna(rsi.iloc[-1]) else None
        
        # Create working dataframe
        work_df = pd.DataFrame({
            'Close': close_prices,
            'MA3': ma3
        })
        work_df = work_df.dropna()
        
        if len(work_df) < 5:
            return None
        
        # Find segments where Close < MA3
        work_df['Below_MA3'] = work_df['Close'] < work_df['MA3']
        
        # Find continuous segments
        segments = []
        in_segment = False
        start_idx = 0
        
        for i in range(len(work_df)):
            if work_df['Below_MA3'].iloc[i] and not in_segment:
                in_segment = True
                start_idx = i
            elif not work_df['Below_MA3'].iloc[i] and in_segment:
                in_segment = False
                segments.append((start_idx, i - 1))
        
        if in_segment:
            segments.append((start_idx, len(work_df) - 1))
        
        # Find reversal points (lowest point in each segment)
        reversal_points = []
        for start, end in segments:
            segment = work_df.iloc[start:end + 1]
            reversal_idx = segment['Close'].idxmin()
            reversal_points.append(reversal_idx)
        
        if not reversal_points:
            return None
        
        # Get the most recent reversal point
        last_reversal = reversal_points[-1]
        last_reversal_price = float(work_df.loc[last_reversal, 'Close'])
        
        # Current data
        current_price = float(work_df['Close'].iloc[-1])
        current_date = work_df.index[-1]
        
        # Calculate DG (Days Gone)
        days_gone = (current_date - last_reversal).days
        
        # Calculate GG (Gains Gone)
        gains_gone = ((current_price - last_reversal_price) / last_reversal_price) * 100
        
        # Calculate period gains
        def calc_period_gain(days):
            if len(work_df) > days:
                past_price = float(work_df['Close'].iloc[-days - 1])
                return ((current_price - past_price) / past_price) * 100
            return 0.0
        
        gain_1d = calc_period_gain(1)
        gain_3d = calc_period_gain(3)
        gain_5d = calc_period_gain(5)
        gain_20d = calc_period_gain(20)
        
        return {
            'sym': symbol,
            'dg': days_gone,
            'gg': round(gains_gone, 2),
            'd1': round(gain_1d, 2),
            'd3': round(gain_3d, 2),
            'd5': round(gain_5d, 2),
            'd20': round(gain_20d, 2),
            'rsi': round(current_rsi, 1) if current_rsi else None
        }
        
    except Exception as e:
        print(f"Error processing {symbol}: {e}")
        return None


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/symbols', methods=['GET'])
def get_symbols():
    """Get current symbol list"""
    symbols = load_symbols()
    return jsonify({'symbols': sorted(symbols), 'count': len(symbols)})


@app.route('/api/storage-status', methods=['GET'])
def get_storage_status():
    """Expose the current write mode for symbols and SIM."""
    return jsonify({
        'storage': 'google_sheets',
        'write_enabled': True,
        'shared_write_enabled': has_shared_sheet_write_access(),
        'write_mode': get_write_mode(),
        'message': '' if has_shared_sheet_write_access() else write_access_error_message(),
    })


@app.route('/api/symbols/add', methods=['POST'])
def add_symbol():
    """Add a new symbol"""
    data = request.get_json()
    symbol = data.get('symbol', '').upper().strip()
    
    if not symbol:
        return jsonify({'error': 'Symbol is required'}), 400
    
    # Validate symbol exists
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.history(period="5d")
        if info.empty:
            return jsonify({'error': f'Invalid symbol: {symbol}'}), 400
    except:
        return jsonify({'error': f'Invalid symbol: {symbol}'}), 400
    
    symbols = load_symbols()
    if symbol in symbols:
        return jsonify({'error': f'{symbol} already exists'}), 400
    
    success, error = add_symbol_to_db(symbol)
    if success:
        shared_write = has_shared_sheet_write_access()
        return jsonify({
            'success': True,
            'symbol': symbol,
            'count': len(symbols) + 1,
            'shared_write': shared_write,
            'write_mode': get_write_mode(),
            'message': '' if shared_write else write_access_error_message(),
        })
    return jsonify({'error': error or 'Failed to add symbol'}), 500


@app.route('/api/symbols/remove', methods=['POST'])
def remove_symbol():
    """Remove a symbol"""
    data = request.get_json()
    symbol = data.get('symbol', '').upper().strip()
    
    if not symbol:
        return jsonify({'error': 'Symbol is required'}), 400
    
    symbols = load_symbols()
    if symbol not in symbols:
        return jsonify({'error': f'{symbol} not found'}), 404
    
    success, error = remove_symbol_from_db(symbol)
    if success:
        shared_write = has_shared_sheet_write_access()
        return jsonify({
            'success': True,
            'symbol': symbol,
            'count': len(symbols) - 1,
            'shared_write': shared_write,
            'write_mode': get_write_mode(),
            'message': '' if shared_write else write_access_error_message(),
        })
    return jsonify({'error': error or 'Failed to remove symbol'}), 500


@app.route('/api/chart/<symbol>')
def get_chart_data(symbol):
    """Get price chart data for a specific symbol"""
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period="60d")
        
        if df.empty:
            return jsonify({"error": "No data found"}), 404
        
        close_prices = df['Close'].copy()
        ma3 = close_prices.rolling(window=3).mean()
        
        work_df =pd.DataFrame({
            'Close': close_prices,
            'MA3': ma3
        })
        work_df = work_df.dropna()
        
        work_df['Below_MA3'] = work_df['Close'] < work_df['MA3']
        segments = []
        in_segment = False
        start_idx = 0
        
        for i in range(len(work_df)):
            if work_df['Below_MA3'].iloc[i] and not in_segment:
                in_segment = True
                start_idx = i
            elif not work_df['Below_MA3'].iloc[i] and in_segment:
                in_segment = False
                segments.append((start_idx, i - 1))
        
        if in_segment:
            segments.append((start_idx, len(work_df) - 1))
        
        reversal_points = []
        for start, end in segments:
            segment = work_df.iloc[start:end + 1]
            reversal_idx = segment['Close'].idxmin()
            reversal_points.append({
                'date': reversal_idx.strftime('%Y-%m-%d'),
                'price': float(work_df.loc[reversal_idx, 'Close'])
            })
        
        chart_data = {
            'dates': [d.strftime('%Y-%m-%d') for d in work_df.index],
            'prices': [float(p) for p in work_df['Close']],
            'ma3': [float(m) for m in work_df['MA3']],
            'reversals': reversal_points,
            'symbol': symbol
        }
        
        return jsonify(chart_data)
        
    except Exception as e:
        print(f"Error getting chart data for {symbol}: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/data')
def get_data():
    """Fetch all symbol data with batch download"""
    global DATA_CACHE
    
    now = time.time()
    force_refresh = request.args.get('refresh', '').lower() in ('1', 'true', 'yes')
    symbols = load_symbols()

    # Serve cache when fresh, but merge in any symbols added since last fetch
    if (
        not force_refresh
        and DATA_CACHE['data']
        and (now - DATA_CACHE['timestamp']) < CACHE_TTL
    ):
        print("Returning cached data (merged with current symbol list)")
        merged = merge_missing_symbols(DATA_CACHE['data'], symbols)
        return jsonify(merged)

    print("Fetching data with batch download...")
    try:
        results = batch_calculate_all(symbols)
        results = merge_missing_symbols(results, symbols)
        print(f"Got {len(results)} results ({len(symbols)} symbols configured)")

        DATA_CACHE = {'data': results, 'timestamp': now}
        return jsonify(results)
        
    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/sim')
def sim_page():
    """Render the universal SIM portfolio page"""
    return render_template('sim.html')


@app.route('/sim/rh')
def sim_rh_page():
    """Redirect the retired RH page to the single SIM portfolio"""
    return redirect('/sim')


@app.route('/sim/df')
def sim_df_page():
    """Redirect the retired DF page to the single SIM portfolio"""
    return redirect('/sim')


@app.route('/api/sim/price/<symbol>')
def get_sim_price(symbol):
    """Get current price and change percent for SIM"""
    try:
        ticker = yf.Ticker(symbol.upper())
        hist = ticker.history(period="2d")
        
        if hist.empty or len(hist) < 1:
            return jsonify({"error": "No data"}), 404
        
        current_price = float(hist['Close'].iloc[-1])
        
        # Calculate change percent from previous close
        if len(hist) >= 2:
            prev_close = float(hist['Close'].iloc[-2])
            change_percent = ((current_price - prev_close) / prev_close) * 100
        else:
            change_percent = 0
        
        return jsonify({
            "symbol": symbol.upper(),
            "price": round(current_price, 2),
            "change_percent": round(change_percent, 2)
        })
        
    except Exception as e:
        print(f"Error getting SIM price for {symbol}: {e}")
        return jsonify({"error": str(e)}), 500


# SIM Portfolio API endpoints
@app.route('/api/sim/positions', methods=['GET'])
def get_sim_positions():
    """Get all active SIM positions from Google Sheets."""
    try:
        return jsonify(load_sim_positions_from_sheet())
    except Exception as e:
        print(f"Error getting SIM positions: {e}")
        return jsonify([])


@app.route('/api/sim/positions', methods=['POST'])
def add_sim_position():
    """Add or update a SIM position"""
    data = request.get_json()
    symbol = data.get('symbol', '').upper().strip()
    shares = data.get('shares')
    cost = data.get('cost')
    buy_date = str(data.get('buy_date', '')).strip()

    if not symbol or shares is None or cost is None:
        return jsonify({'error': 'Missing required fields'}), 400

    try:
        shares = float(shares)
        cost = float(cost)
    except (TypeError, ValueError):
        return jsonify({'error': 'Shares and cost must be numbers'}), 400

    if shares <= 0 or cost <= 0:
        return jsonify({'error': 'Shares and cost must be greater than zero'}), 400
    
    try:
        success, error = upsert_sim_position_in_sheet(symbol, shares, cost, buy_date)
        if not success:
            return jsonify({'error': error or 'Failed to save SIM position'}), 500
        return jsonify({'success': True})
    except Exception as e:
        print(f"Error adding SIM position: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/sim/positions/<symbol>', methods=['DELETE'])
def delete_sim_position(symbol):
    """Delete a SIM position"""
    try:
        success, error = delete_sim_position_from_sheet(symbol.upper())
        if not success:
            return jsonify({'error': error or 'Failed to delete SIM position'}), 500
        return jsonify({'success': True})
    except Exception as e:
        print(f"Error deleting SIM position: {e}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    print(f"Starting server with {len(load_symbols())} symbols...")
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, port=port, host='0.0.0.0')
