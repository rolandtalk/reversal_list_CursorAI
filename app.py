"""
Stock Reversal Point Analysis Web App
Based on MA3 reversal point detection algorithm
"""

from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
import warnings
warnings.filterwarnings('ignore')

# Supabase
from supabase import create_client, Client
import time

app = Flask(__name__, static_folder='static')
CORS(app)

# Simple cache
DATA_CACHE = {'data': None, 'timestamp': 0}
CACHE_TTL = 300  # 5 minutes

# Supabase configuration
SUPABASE_URL = os.environ.get('SUPABASE_URL', 'https://pggshikvapdnukpzoznk.supabase.co')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY', 'sb_publishable_BgGQTZmkECmAwRAOM6Bmig_uTafg82R')

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# This deployment's public URL (dupe repo — avoid confusion with production)
APP_BASE_URL = os.environ.get('APP_BASE_URL', 'https://reversalX.up.railway.app')


@app.context_processor
def inject_base_url():
    return {'base_url': APP_BASE_URL}


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
    """Load symbols from Supabase"""
    try:
        response = supabase.table('symbols').select('symbol').execute()
        if response.data:
            return [row['symbol'] for row in response.data]
        else:
            # Initialize with default symbols if table is empty
            init_default_symbols()
            return DEFAULT_SYMBOLS.copy()
    except Exception as e:
        print(f"Error loading symbols from Supabase: {e}")
        return DEFAULT_SYMBOLS.copy()

def init_default_symbols():
    """Initialize database with default symbols"""
    try:
        for symbol in DEFAULT_SYMBOLS:
            supabase.table('symbols').upsert({'symbol': symbol}).execute()
        print("Initialized default symbols in Supabase")
    except Exception as e:
        print(f"Error initializing symbols: {e}")

def add_symbol_to_db(symbol):
    """Add a symbol to Supabase"""
    try:
        supabase.table('symbols').insert({'symbol': symbol}).execute()
        return True
    except Exception as e:
        print(f"Error adding symbol: {e}")
        return False

def remove_symbol_from_db(symbol):
    """Remove a symbol from Supabase"""
    try:
        supabase.table('symbols').delete().eq('symbol', symbol).execute()
        return True
    except Exception as e:
        print(f"Error removing symbol: {e}")
        return False

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
        data = yf.download(symbols, period="40d", group_by='ticker', progress=False, threads=True)
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
    
    if add_symbol_to_db(symbol):
        return jsonify({'success': True, 'symbol': symbol, 'count': len(symbols) + 1})
    else:
        return jsonify({'error': 'Failed to add symbol'}), 500


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
    
    if remove_symbol_from_db(symbol):
        return jsonify({'success': True, 'symbol': symbol, 'count': len(symbols) - 1})
    else:
        return jsonify({'error': 'Failed to remove symbol'}), 500


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
    """Redirect to SIM RH page"""
    return render_template('sim.html')


@app.route('/sim/rh')
def sim_rh_page():
    """Render SIM RH portfolio page"""
    return render_template('sim.html')


@app.route('/sim/df')
def sim_df_page():
    """Render SIM DF portfolio page"""
    return render_template('sim_df.html')


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
    """Get all SIM positions from Supabase"""
    try:
        response = supabase.table('sim_positions').select('*').execute()
        return jsonify(response.data if response.data else [])
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
    buy_date = data.get('buy_date', '')
    
    if not symbol or shares is None or cost is None:
        return jsonify({'error': 'Missing required fields'}), 400
    
    try:
        supabase.table('sim_positions').upsert({
            'symbol': symbol,
            'shares': float(shares),
            'cost': float(cost),
            'buy_date': buy_date
        }).execute()
        return jsonify({'success': True})
    except Exception as e:
        print(f"Error adding SIM position: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/sim/positions/<symbol>', methods=['DELETE'])
def delete_sim_position(symbol):
    """Delete a SIM position"""
    try:
        supabase.table('sim_positions').delete().eq('symbol', symbol.upper()).execute()
        return jsonify({'success': True})
    except Exception as e:
        print(f"Error deleting SIM position: {e}")
        return jsonify({'error': str(e)}), 500


# SIM DF Portfolio API endpoints
@app.route('/api/sim/df/positions', methods=['GET'])
def get_sim_df_positions():
    """Get all SIM DF positions from Supabase"""
    try:
        response = supabase.table('sim_positions_df').select('*').execute()
        return jsonify(response.data if response.data else [])
    except Exception as e:
        print(f"Error getting SIM DF positions: {e}")
        return jsonify([])


@app.route('/api/sim/df/positions', methods=['POST'])
def add_sim_df_position():
    """Add or update a SIM DF position"""
    data = request.get_json()
    symbol = data.get('symbol', '').upper().strip()
    shares = data.get('shares')
    cost = data.get('cost')
    buy_date = data.get('buy_date', '')
    
    if not symbol or shares is None or cost is None:
        return jsonify({'error': 'Missing required fields'}), 400
    
    try:
        supabase.table('sim_positions_df').upsert({
            'symbol': symbol,
            'shares': float(shares),
            'cost': float(cost),
            'buy_date': buy_date
        }).execute()
        return jsonify({'success': True})
    except Exception as e:
        print(f"Error adding SIM DF position: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/sim/df/positions/<symbol>', methods=['DELETE'])
def delete_sim_df_position(symbol):
    """Delete a SIM DF position"""
    try:
        supabase.table('sim_positions_df').delete().eq('symbol', symbol.upper()).execute()
        return jsonify({'success': True})
    except Exception as e:
        print(f"Error deleting SIM DF position: {e}")
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    print(f"Starting server with {len(load_symbols())} symbols...")
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, port=port, host='0.0.0.0')
