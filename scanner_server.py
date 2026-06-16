"""
Scanner v10 - Paper Trading Backend Server
Flask server that provides Yahoo Finance data, indicator calculations,
and portfolio management for the Scanner v10 HTML frontend.
"""
import json
import os
from datetime import datetime, timedelta
from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS
import yfinance as yf
import pandas as pd
import numpy as np

app = Flask(__name__, static_folder='.')
CORS(app)

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
os.makedirs(DATA_DIR, exist_ok=True)

INDICES = {
    'NIFTY 50': '^NSEI',
    'NIFTY BANK': '^NSEBANK',
    'NIFTY IT': '^CNXIT',
    'NIFTY AUTO': '^CNXAUTO',
    'NIFTY PHARMA': '^CNXPHARMA',
    'NIFTY FMCG': '^CNXFMCG',
    'NIFTY METAL': '^CNXMETAL',
    'NIFTY REALTY': '^CNXREALTY',
    'NIFTY ENERGY': '^CNXENERGY',
    'NIFTY PSU BANK': '^CNXPSUBANK',
    'NIFTY MNC': '^CNXMNC',
}

CAPITAL = 1000000
TOP_N = 3
CONFIG = {
    'entry_mode': 'v9e_default',
    'min_score': 150,
    'rebal_freq': 'monthly',
    'stop_type': 'none',
}

def compute_indicators(df):
    """Compute all technical indicators for a DataFrame."""
    df = df.copy()
    
    df['RSI_4'] = compute_rsi(df['Close'], 4)
    df['RSI_8'] = compute_rsi(df['Close'], 8)
    df['RSI_14'] = compute_rsi(df['Close'], 14)
    
    df['WMA_5'] = compute_wma(df['Close'], 5)
    df['WMA_8'] = compute_wma(df['Close'], 8)
    df['WMA_14'] = compute_wma(df['Close'], 14)
    df['WMA_20'] = compute_wma(df['Close'], 20)
    
    df['MACD'], df['MACD_Signal'], df['MACD_Hist'] = compute_macd(df['Close'])
    df['ADX'], df['Plus_DI'], df['Minus_DI'] = compute_adx(df['High'], df['Low'], df['Close'], 14)
    
    df['BB_Upper'], df['BB_Middle'], df['BB_Lower'] = compute_bollinger(df['Close'], 20, 2)
    df['BB_PctB'] = (df['Close'] - df['BB_Lower']) / (df['BB_Upper'] - df['BB_Lower'])
    df['BB_Width'] = (df['BB_Upper'] - df['BB_Lower']) / df['BB_Middle']
    
    df['STOCH_K'], df['STOCH_D'] = compute_stoch_rsi(df['Close'], 14, 3, 3)
    df['OBV'] = compute_obv(df['Close'], df['Volume'])
    df['OBV_SMA'] = df['OBV'].rolling(20).mean()
    df['ATR'] = compute_atr(df['High'], df['Low'], df['Close'], 14)
    df['ATR_Pct'] = df['ATR'] / df['Close'] * 100
    df['Williams_R'] = compute_williams_r(df['High'], df['Low'], df['Close'], 14)
    df['CCI'] = compute_cci(df['High'], df['Low'], df['Close'], 20)
    df['PSAR'] = compute_psar(df['High'], df['Low'])
    df['VWAP'] = compute_vwap(df['High'], df['Low'], df['Close'], df['Volume'])
    
    df['Regime'] = df.apply(get_regime, axis=1)
    df['V9E_Score'] = df.apply(compute_v9e_score, axis=1)
    
    return df

def compute_rsi(series, period):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def compute_wma(series, period):
    weights = np.arange(1, period + 1)
    return series.rolling(period).apply(lambda x: np.dot(x, weights) / weights.sum(), raw=True)

def compute_macd(series, fast=12, slow=26, signal=9):
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    signal_line = macd.ewm(span=signal, adjust=False).mean()
    histogram = macd - signal_line
    return macd, signal_line, histogram

def compute_adx(high, low, close, period=14):
    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0)
    tr1 = high - low
    tr2 = abs(high - close.shift())
    tr3 = abs(low - close.shift())
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/period, adjust=False).mean()
    plus_di = 100 * (plus_dm.ewm(alpha=1/period, adjust=False).mean() / atr)
    minus_di = 100 * (minus_dm.ewm(alpha=1/period, adjust=False).mean() / atr)
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
    adx = dx.ewm(alpha=1/period, adjust=False).mean()
    return adx, plus_di, minus_di

def compute_bollinger(series, period=20, std=2):
    middle = series.rolling(period).mean()
    std_dev = series.rolling(period).std()
    upper = middle + std * std_dev
    lower = middle - std * std_dev
    return upper, middle, lower

def compute_stoch_rsi(series, rsi_period=14, stoch_period=3, k_period=3, d_period=3):
    rsi = compute_rsi(series, rsi_period)
    stoch_rsi = (rsi - rsi.rolling(stoch_period).min()) / (rsi.rolling(stoch_period).max() - rsi.rolling(stoch_period).min())
    k = stoch_rsi.rolling(k_period).mean() * 100
    d = k.rolling(d_period).mean()
    return k, d

def compute_obv(close, volume):
    obv = [0]
    for i in range(1, len(close)):
        if close.iloc[i] > close.iloc[i-1]:
            obv.append(obv[-1] + volume.iloc[i])
        elif close.iloc[i] < close.iloc[i-1]:
            obv.append(obv[-1] - volume.iloc[i])
        else:
            obv.append(obv[-1])
    return pd.Series(obv, index=close.index)

def compute_atr(high, low, close, period=14):
    tr1 = high - low
    tr2 = abs(high - close.shift())
    tr3 = abs(low - close.shift())
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.ewm(alpha=1/period, adjust=False).mean()

def compute_williams_r(high, low, close, period=14):
    highest = high.rolling(period).max()
    lowest = low.rolling(period).min()
    return -100 * (highest - close) / (highest - lowest)

def compute_cci(high, low, close, period=20):
    tp = (high + low + close) / 3
    sma = tp.rolling(period).mean()
    mad = tp.rolling(period).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
    return (tp - sma) / (0.015 * mad)

def compute_psar(high, low, af_start=0.02, af_step=0.02, af_max=0.2):
    length = len(high)
    psar = np.zeros(length)
    af = af_start
    bull = True
    ep = low.iloc[0]
    hp = high.iloc[0]
    lp = low.iloc[0]
    psar[0] = high.iloc[0]
    
    for i in range(1, length):
        if bull:
            psar[i] = psar[i-1] + af * (hp - psar[i-1])
            psar[i] = min(psar[i], low.iloc[i-1])
            if i >= 2:
                psar[i] = min(psar[i], low.iloc[i-2])
            if low.iloc[i] < psar[i]:
                bull = False
                psar[i] = hp
                lp = low.iloc[i]
                af = af_start
            else:
                if high.iloc[i] > hp:
                    hp = high.iloc[i]
                    af = min(af + af_step, af_max)
        else:
            psar[i] = psar[i-1] + af * (lp - psar[i-1])
            psar[i] = max(psar[i], high.iloc[i-1])
            if i >= 2:
                psar[i] = max(psar[i], high.iloc[i-2])
            if high.iloc[i] > psar[i]:
                bull = True
                psar[i] = lp
                hp = high.iloc[i]
                af = af_start
            else:
                if low.iloc[i] < lp:
                    lp = low.iloc[i]
                    af = min(af + af_step, af_max)
    
    return pd.Series(psar, index=high.index)

def compute_vwap(high, low, close, volume):
    tp = (high + low + close) / 3
    vwap = (tp * volume).cumsum() / volume.cumsum()
    return vwap

def get_regime(row):
    rsi4 = row.get('RSI_4', 50)
    rsi8 = row.get('RSI_8', 50)
    rsi14 = row.get('RSI_14', 50)
    macd_hist = row.get('MACD_Hist', 0)
    adx = row.get('ADX', 20)
    
    bull_score = 0
    if rsi4 > 50: bull_score += 1
    if rsi8 > 50: bull_score += 1
    if rsi14 > 50: bull_score += 1
    if macd_hist > 0: bull_score += 1
    if adx > 25: bull_score += 1
    
    if bull_score >= 4: return 'A'
    if bull_score >= 2: return 'B'
    return 'C'

def compute_v9e_score(row):
    score = 0
    rsi4 = row.get('RSI_4', 50)
    rsi8 = row.get('RSI_8', 50)
    rsi14 = row.get('RSI_14', 50)
    macd_hist = row.get('MACD_Hist', 0)
    adx = row.get('ADX', 20)
    
    if 40 <= rsi4 <= 60: score += 50
    elif 30 <= rsi4 <= 70: score += 30
    if 40 <= rsi8 <= 60: score += 40
    elif 30 <= rsi8 <= 70: score += 20
    if 40 <= rsi14 <= 60: score += 30
    elif 30 <= rsi14 <= 70: score += 10
    
    if macd_hist > 0: score += 30
    if adx > 25: score += 20
    if row.get('Regime') == 'A': score += 30
    
    bb_pctb = row.get('BB_PctB', 0.5)
    if 0.2 < bb_pctb < 0.8: score += 10
    
    return score

@app.route('/')
def index():
    return send_from_directory('.', 'scanner_v10_paper.html')

@app.route('/api/scan')
def api_scan():
    all_data = {}
    for name, symbol in INDICES.items():
        cache_file = os.path.join(DATA_DIR, f'{symbol.replace("^", "").replace(" ", "_")}.csv')
        
        if os.path.exists(cache_file):
            mod_time = os.path.getmtime(cache_file)
            if (datetime.now() - datetime.fromtimestamp(mod_time)).days < 1:
                df = pd.read_csv(cache_file, index_col=0, parse_dates=True)
                all_data[name] = df
                continue
        
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period='2y')
            if len(df) > 0:
                df.to_csv(cache_file)
                all_data[name] = df
        except Exception as e:
            print(f"Error fetching {name}: {e}")
    
    results = []
    for name, df in all_data.items():
        if len(df) < 50:
            continue
        
        df = compute_indicators(df)
        last = df.iloc[-1]
        
        results.append({
            'name': name,
            'symbol': INDICES[name],
            'price': round(float(last['Close']), 2),
            'rsi4': round(float(last['RSI_4']), 1) if not np.isnan(last['RSI_4']) else 50,
            'rsi8': round(float(last['RSI_8']), 1) if not np.isnan(last['RSI_8']) else 50,
            'rsi14': round(float(last['RSI_14']), 1) if not np.isnan(last['RSI_14']) else 50,
            'macd_hist': round(float(last['MACD_Hist']), 2) if not np.isnan(last['MACD_Hist']) else 0,
            'adx': round(float(last['ADX']), 1) if not np.isnan(last['ADX']) else 20,
            'regime': last['Regime'],
            'score': int(last['V9E_Score']),
            'bb_pctb': round(float(last['BB_PctB']), 2) if not np.isnan(last['BB_PctB']) else 0.5,
            'stoch_k': round(float(last['STOCH_K']), 1) if not np.isnan(last['STOCH_K']) else 50,
            'williams_r': round(float(last['Williams_R']), 1) if not np.isnan(last['Williams_R']) else -50,
            'cci': round(float(last['CCI']), 1) if not np.isnan(last['CCI']) else 0,
        })
    
    results.sort(key=lambda x: x['score'], reverse=True)
    return jsonify(results)

@app.route('/api/portfolio')
def api_portfolio():
    portfolio_file = os.path.join(DATA_DIR, 'portfolio.json')
    if os.path.exists(portfolio_file):
        with open(portfolio_file, 'r') as f:
            return jsonify(json.load(f))
    return jsonify({'cash': CAPITAL, 'positions': {}, 'trades': []})

@app.route('/api/portfolio/update', methods=['POST'])
def api_portfolio_update():
    from flask import request
    data = request.json
    portfolio_file = os.path.join(DATA_DIR, 'portfolio.json')
    with open(portfolio_file, 'w') as f:
        json.dump(data, f, indent=2)
    return jsonify({'status': 'ok'})

if __name__ == '__main__':
    print("Scanner v10 Paper Trading Server")
    print("Open http://localhost:5000 in your browser")
    app.run(debug=True, port=5000)
