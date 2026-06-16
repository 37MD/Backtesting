"""
Scanner v9E Backtest v3 — REBALANCING FREQUENCY + NEW INDICATORS
Tests: daily / bi-weekly / monthly rebalancing
Adds: MACD(12,26,9), ADX(14), RS vs NIFTY 50
Combines with best v2 entry configs (RELAXED)
"""

import json
import os
import warnings
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

# ============================================================
# UNIVERSE — 14 working NSE index ETFs
# ============================================================
SYMBOLS = {
    "NIFTY 50":          "^NSEI",
    "NIFTY BANK":        "^NSEBANK",
    "NIFTY IT":          "^CNXIT",
    "NIFTY AUTO":        "^CNXAUTO",
    "NIFTY PHARMA":      "^CNXPHARMA",
    "NIFTY FMCG":        "^CNXFMCG",
    "NIFTY METAL":       "^CNXMETAL",
    "NIFTY REALTY":      "^CNXREALTY",
    "NIFTY ENERGY":      "^CNXENERGY",
    "NIFTY NEXT 50":     "^NIFTYNXT50",
    "NIFTY SMALLCAP 250":"^NSESMALLCAP",
    "NIFTY PSU BANK":    "^CNXPSUBANK",
    "NIFTY HEALTHCARE":  "^CNXHEALTHCARE",
    "NIFTY MNC":         "^CNXMNC",
}

START = "2021-01-01"
END   = "2026-06-15"
CAPITAL = 1000000
TOP_N = 3
COMMISSION_PCT = 0.05

# ============================================================
# INDICATORS
# ============================================================
def rsi_wilder(series, period):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def wma(series, period):
    weights = np.arange(1, period + 1)
    return series.rolling(period).apply(lambda x: np.dot(x, weights) / weights.sum(), raw=True)

def ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def compute_macd(close, fast=12, slow=26, signal=9):
    ema_fast = ema(close, fast)
    ema_slow = ema(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram

def compute_adx(high, low, close, period=14):
    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm[plus_dm < 0] = 0
    minus_dm[minus_dm < 0] = 0
    plus_dm[(plus_dm < minus_dm)] = 0
    minus_dm[(minus_dm < plus_dm)] = 0

    tr1 = high - low
    tr2 = abs(high - close.shift())
    tr3 = abs(low - close.shift())
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr = tr.ewm(alpha=1/period, min_periods=period).mean()
    plus_di = 100 * (plus_dm.ewm(alpha=1/period, min_periods=period).mean() / atr)
    minus_di = 100 * (minus_dm.ewm(alpha=1/period, min_periods=period).mean() / atr)

    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di + 1e-10)
    adx = dx.ewm(alpha=1/period, min_periods=period).mean()
    return adx, plus_di, minus_di

def add_indicators(df):
    c = df["Close"]
    df["RSI4"]  = rsi_wilder(c, 4)
    df["RSI8"]  = rsi_wilder(c, 8)
    df["RSI14"] = rsi_wilder(c, 14)
    df["WMA20"] = wma(c, 20)
    df["WMA50"] = wma(c, 50)

    df["MACD"], df["MACD_signal"], df["MACD_hist"] = compute_macd(c)
    df["ADX"], df["PlusDI"], df["MinusDI"] = compute_adx(df["High"], df["Low"], c)

    df["Chg"] = c.pct_change()
    df["Chg_10"] = c.pct_change(10)

    h = c.rolling(10).max()
    l = c.rolling(10).min()
    df["HA_Band"] = (c - l) / (h - l + 1e-10) * 100

    return df

# ============================================================
# SCORING
# ============================================================
def compute_score(row, use_macd=False, use_adx=False, use_rs=False, rs_value=None):
    score = 0
    r4  = row["RSI4"]
    r8  = row["RSI8"]
    r14 = row["RSI14"]

    if np.isnan(r4) or np.isnan(r8) or np.isnan(r14):
        return -999

    # RSI scoring
    if r4 > 80: score += 50
    elif r4 > 70: score += 40
    elif r4 > 60: score += 30
    elif r4 > 50: score += 20
    elif r4 > 40: score += 10

    if r8 > 70: score += 40
    elif r8 > 60: score += 30
    elif r8 > 50: score += 20
    elif r8 > 40: score += 10

    if r14 > 60: score += 30
    elif r14 > 50: score += 20
    elif r14 > 40: score += 10

    # RSI alignment bonus
    if r4 > r8 > r14: score += 20

    # MACD bonus
    if use_macd:
        macd_hist = row.get("MACD_hist", np.nan)
        if not np.isnan(macd_hist):
            if macd_hist > 0:
                score += 20
            else:
                score -= 10

    # ADX bonus
    if use_adx:
        adx = row.get("ADX", np.nan)
        plus_di = row.get("PlusDI", np.nan)
        minus_di = row.get("MinusDI", np.nan)
        if not np.isnan(adx) and not np.isnan(plus_di) and not np.isnan(minus_di):
            if adx > 25 and plus_di > minus_di:
                score += 25  # strong uptrend
            elif adx > 20 and plus_di > minus_di:
                score += 15
            elif adx > 25 and plus_di < minus_di:
                score -= 15  # strong downtrend

    # RS vs NIFTY 50 bonus
    if use_rs and rs_value is not None and not np.isnan(rs_value):
        if rs_value > 1.10: score += 25
        elif rs_value > 1.05: score += 15
        elif rs_value > 1.00: score += 5

    return score

def classify_regime(row):
    r4  = row["RSI4"]
    r8  = row["RSI8"]
    r14 = row["RSI14"]
    w20 = row["WMA20"]
    price = row["Close"]

    if np.isnan(r4) or np.isnan(r8) or np.isnan(r14):
        return "C"

    above_wma = price > w20 if not np.isnan(w20) else True

    if r4 > 60 and r8 > 55 and r14 > 50 and above_wma:
        return "A"
    elif r4 < 40 and r8 < 45 and r14 < 50:
        return "C"
    else:
        return "B"

# ============================================================
# REBALANCE SCHEDULERS
# ============================================================
def get_rebalance_dates(dates, freq):
    """Return list of dates when we should rebalance."""
    if freq == "daily":
        return list(dates)
    elif freq == "weekly":
        # Every Friday (or last day of week)
        rebal = []
        current_week = None
        for d in dates:
            wk = d.isocalendar()[1]
            if current_week is not None and wk != current_week:
                rebal.append(prev_d)
            current_week = wk
            prev_d = d
        rebal.append(dates[-1])
        return rebal
    elif freq == "biweekly":
        rebal = []
        count = 0
        for i, d in enumerate(dates):
            if i == 0:
                continue
            prev_d = dates[i-1]
            diff = (d - prev_d).days
            count += diff
            if count >= 10:  # ~10 trading days = 2 weeks
                rebal.append(prev_d)
                count = 0
        rebal.append(dates[-1])
        return rebal
    elif freq == "monthly":
        rebal = []
        current_month = None
        for d in dates:
            m = (d.year, d.month)
            if current_month is not None and m != current_month:
                rebal.append(prev_d)
            current_month = m
            prev_d = d
        rebal.append(dates[-1])
        return rebal
    else:
        return list(dates)

# ============================================================
# BACKTEST ENGINE
# ============================================================
def backtest(data, config, rebal_freq, capital, top_n):
    """
    config: dict with keys:
        entry_mode: "relaxed" / "regime_a" / "v9e_default"
        use_macd: bool
        use_adx: bool
        use_rs: bool
        min_score: int
        require_ha_band: bool
        stop_type: "none" / "wma20" / "trail_2.5" / "trail_3" / "trail_4"
        min_adx: int (if use_adx)
    """
    entry_mode = config.get("entry_mode", "relaxed")
    use_macd = config.get("use_macd", False)
    use_adx = config.get("use_adx", False)
    use_rs = config.get("use_rs", False)
    min_score = config.get("min_score", 120)
    require_ha_band = config.get("require_ha_band", False)
    stop_type = config.get("stop_type", "none")
    min_adx = config.get("min_adx", 20)

    cash = capital
    positions = {}  # name -> {shares, buy_price, buy_date, peak_price}
    trades = []
    equity_curve = []

    # Build NIFTY 50 for RS calculation
    nifty50_data = data.get("NIFTY 50")
    nifty50_rsi14 = nifty50_data["RSI14"] if nifty50_data is not None else None

    all_dates = sorted(set().union(*[set(d.index) for d in data.values() if d is not None]))

    # Filter to only dates where all 14 indices have data
    # Use majority (at least 10) for scoring
    rebal_dates = get_rebalance_dates(all_dates, rebal_freq)

    peak_prices = {}

    for date in rebal_dates:
        # Update peak prices for trailing stop
        for name, pos in list(positions.items()):
            if name in data and data[name] is not None and date in data[name].index:
                current_price = data[name].loc[date, "Close"]
                if name not in peak_prices or current_price > peak_prices[name]:
                    peak_prices[name] = current_price

        # Check stop losses first
        for name in list(positions.keys()):
            if name not in data or data[name] is None or date not in data[name].index:
                continue
            pos = positions[name]
            current_price = data[name].loc[date, "Close"]
            sell = False
            reason = ""

            if stop_type == "wma20":
                wma20 = data[name].loc[date, "WMA20"]
                if not np.isnan(wma20) and current_price < wma20:
                    sell = True
                    reason = "WMA20 stop"

            elif stop_type.startswith("trail_"):
                pct = float(stop_type.split("_")[1]) / 100
                peak = peak_prices.get(name, pos["buy_price"])
                if current_price < peak * (1 - pct):
                    sell = True
                    reason = f"Trail {pct*100:.1f}% stop"

            if sell:
                ret = (current_price - pos["buy_price"]) / pos["buy_price"] * 100
                commission = current_price * pos["shares"] * COMMISSION_PCT / 100
                proceeds = current_price * pos["shares"] - commission
                cash += proceeds
                trades.append({
                    "date": date, "action": "SELL", "name": name,
                    "price": current_price, "shares": pos["shares"],
                    "buy_date": pos["buy_date"], "buy_price": pos["buy_price"],
                    "reason": reason, "return_pct": ret, "proceeds": proceeds
                })
                del positions[name]
                if name in peak_prices:
                    del peak_prices[name]

        # Exit regime B/C positions
        for name in list(positions.keys()):
            if name not in data or data[name] is None or date not in data[name].index:
                continue
            pos = positions[name]
            current_price = data[name].loc[date, "Close"]
            regime = classify_regime(data[name].loc[date])

            if entry_mode == "relaxed":
                pass  # hold all
            elif entry_mode == "regime_a" or entry_mode == "v9e_default":
                if regime != "A":
                    ret = (current_price - pos["buy_price"]) / pos["buy_price"] * 100
                    commission = current_price * pos["shares"] * COMMISSION_PCT / 100
                    proceeds = current_price * pos["shares"] - commission
                    cash += proceeds
                    trades.append({
                        "date": date, "action": "SELL", "name": name,
                        "price": current_price, "shares": pos["shares"],
                        "buy_date": pos["buy_date"], "buy_price": pos["buy_price"],
                        "reason": f"Regime {regime} exit", "return_pct": ret, "proceeds": proceeds
                    })
                    del positions[name]
                    if name in peak_prices:
                        del peak_prices[name]

        # Score all indices for potential buys
        scores = {}
        for name, df in data.items():
            if df is None or date not in df.index:
                continue
            if name in positions:
                continue
            row = df.loc[date]

            rs_val = None
            if use_rs and nifty50_rsi14 is not None and date in nifty50_rsi14.index:
                nifty_rsi = nifty50_rsi14.loc[date]
                if not np.isnan(row["RSI14"]) and not np.isnan(nifty_rsi) and nifty_rsi > 0:
                    rs_val = row["RSI14"] / nifty_rsi

            sc = compute_score(row, use_macd=use_macd, use_adx=use_adx, use_rs=use_rs, rs_value=rs_val)

            if sc < min_score:
                continue

            if require_ha_band:
                ha = row.get("HA_Band", np.nan)
                if np.isnan(ha) or ha < 50:
                    continue

            if use_adx:
                adx = row.get("ADX", np.nan)
                if np.isnan(adx) or adx < min_adx:
                    continue

            scores[name] = sc

        # Rank and buy top N
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_n]

        if ranked:
            alloc = cash / len(ranked)
        else:
            alloc = 0

        for name, sc in ranked:
            price = data[name].loc[date, "Close"]
            if price <= 0 or alloc <= 0:
                continue
            shares = alloc / price
            commission = alloc * COMMISSION_PCT / 100
            cash -= (alloc + commission)
            positions[name] = {
                "shares": shares, "buy_price": price, "buy_date": date
            }
            peak_prices[name] = price
            trades.append({
                "date": date, "action": "BUY", "name": name,
                "price": price, "shares": shares,
                "buy_date": date, "buy_price": price,
                "reason": f"Score:{sc:.0f}", "return_pct": 0, "proceeds": 0
            })

        # Record equity
        port_val = cash
        for name, pos in positions.items():
            if name in data and data[name] is not None and date in data[name].index:
                port_val += data[name].loc[date, "Close"] * pos["shares"]
            else:
                port_val += pos["buy_price"] * pos["shares"]
        equity_curve.append({"date": date, "equity": port_val})

    # Final liquidation
    final_date = all_dates[-1]
    for name in list(positions.keys()):
        pos = positions[name]
        if name in data and data[name] is not None and final_date in data[name].index:
            current_price = data[name].loc[final_date, "Close"]
        else:
            current_price = pos["buy_price"]
        ret = (current_price - pos["buy_price"]) / pos["buy_price"] * 100
        commission = current_price * pos["shares"] * COMMISSION_PCT / 100
        proceeds = current_price * pos["shares"] - commission
        cash += proceeds
        trades.append({
            "date": final_date, "action": "SELL", "name": name,
            "price": current_price, "shares": pos["shares"],
            "buy_date": pos["buy_date"], "buy_price": pos["buy_price"],
            "reason": "Final liquidation", "return_pct": ret, "proceeds": proceeds
        })

    # Compute metrics
    equity_df = pd.DataFrame(equity_curve)
    if len(equity_df) < 2:
        return None

    equity_df["date"] = pd.to_datetime(equity_df["date"])
    equity_df = equity_df.set_index("date")

    total_return = (cash - capital) / capital * 100
    years = (equity_df.index[-1] - equity_df.index[0]).days / 365.25
    cagr = ((cash / capital) ** (1 / years) - 1) * 100 if years > 0 else 0

    # Max drawdown
    rolling_max = equity_df["equity"].cummax()
    drawdown = (equity_df["equity"] - rolling_max) / rolling_max * 100
    max_dd = drawdown.min()

    # Win rate
    sell_trades = [t for t in trades if t["action"] == "SELL" and t["reason"] != "Final liquidation"]
    wins = [t for t in sell_trades if t["return_pct"] > 0]
    win_rate = len(wins) / len(sell_trades) * 100 if sell_trades else 0
    avg_win = np.mean([t["return_pct"] for t in wins]) if wins else 0
    losses = [t for t in sell_trades if t["return_pct"] <= 0]
    avg_loss = np.mean([t["return_pct"] for t in losses]) if losses else 0

    # Cash weeks
    total_weeks = len(rebal_dates)
    cash_weeks = 0
    for i, eq in enumerate(equity_curve):
        if i > 0:
            prev_eq = equity_curve[i-1]["equity"]
            # If equity didn't change (all cash)
            if abs(eq["equity"] - cash) < 1:  # approximation
                cash_weeks += 1
    cash_pct = cash_weeks / total_weeks * 100 if total_weeks > 0 else 0

    return {
        "final_value": round(cash),
        "total_return_pct": round(total_return, 2),
        "cagr_pct": round(cagr, 2),
        "max_drawdown_pct": round(abs(max_dd), 2),
        "win_rate_pct": round(win_rate, 1),
        "avg_win_pct": round(avg_win, 2),
        "avg_loss_pct": round(avg_loss, 2),
        "total_trades": len(trades),
        "sell_trades": len(sell_trades),
        "cash_pct": round(cash_pct, 1),
        "trades": trades,
        "equity": equity_curve
    }

# ============================================================
# MAIN
# ============================================================
def main():
    print("=" * 60)
    print("SCANNER v9E BACKTEST v3 — REBALANCING FREQUENCY + NEW INDICATORS")
    print("=" * 60)
    print(f"Period: {START} - {END} | Capital: Rs {CAPITAL:,}")
    print(f"Rebalancing: DAILY / BI-WEEKLY / MONTHLY")
    print(f"Indicators: MACD(12,26,9), ADX(14), RS vs NIFTY 50")
    print()

    # Download
    print("STEP 1: Downloading data...")
    all_data = {}
    for name, ticker in SYMBOLS.items():
        try:
            df = yf.download(ticker, start=START, end=END, progress=False, auto_adjust=True)
            if df is not None and len(df) > 50:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                all_data[name] = df
                print(f"  OK: {name} -> {len(df)} days")
            else:
                print(f"  SKIP: {name} -> insufficient data")
        except Exception as e:
            print(f"  FAIL: {name} -> {e}")
    print(f"\n  Downloaded: {len(all_data)} indices")

    # Add indicators
    print("\nSTEP 2: Computing indicators...")
    for name in list(all_data.keys()):
        try:
            all_data[name] = add_indicators(all_data[name])
            print(f"  OK: {name}")
        except Exception as e:
            print(f"  FAIL: {name}: {e}")
            del all_data[name]

    # Define all configurations
    print("\nSTEP 3: Defining configurations...")

    configs = []

    # Base configs (from v2 best)
    base_entry = [
        ("RELAXED",        {"entry_mode": "relaxed", "min_score": 120, "require_ha_band": False}),
        ("REGIME_A",       {"entry_mode": "regime_a", "min_score": 120, "require_ha_band": False}),
        ("V9E_DEFAULT",    {"entry_mode": "v9e_default", "min_score": 160, "require_ha_band": True}),
    ]

    # Indicator combos
    indicator_combos = [
        ("BASE",               False, False, False, None),
        ("+MACD",              True,  False, False, None),
        ("+ADX",               False, True,  False, 20),
        ("+RS",                False, False, True,  None),
        ("+MACD+ADX",          True,  True,  False, 20),
        ("+MACD+RS",           True,  False, True,  None),
        ("+ADX+RS",            False, True,  True,  20),
        ("+ALL",               True,  True,  True,  20),
    ]

    # Rebalancing frequencies
    rebal_freqs = ["daily", "biweekly", "monthly"]

    # Stop types
    stops = ["none", "wma20", "trail_3"]

    config_id = 0
    for entry_name, entry_params in base_entry:
        for ind_name, use_macd, use_adx, use_rs, min_adx in indicator_combos:
            for freq in rebal_freqs:
                for stop in stops:
                    config_id += 1
                    name = f"{config_id:02d} {entry_name} {ind_name} {freq} {stop}"
                    params = {
                        **entry_params,
                        "use_macd": use_macd,
                        "use_adx": use_adx,
                        "use_rs": use_rs,
                        "stop_type": stop,
                        "min_adx": min_adx or 20,
                    }
                    configs.append((name, params, freq))

    print(f"  Total configurations: {len(configs)}")

    # Run all configs
    print(f"\nSTEP 4: Running {len(configs)} configurations...")
    results = []

    for i, (name, params, freq) in enumerate(configs):
        print(f"\n{'='*60}")
        print(f"CONFIG {i+1:02d}/{len(configs)}  {name}")
        print(f"{'='*60}")

        try:
            r = backtest(all_data, params, freq, CAPITAL, TOP_N)
            if r:
                r["config_name"] = name
                r["config_params"] = params
                r["rebal_freq"] = freq
                results.append(r)
                print(f"  Final: Rs {r['final_value']:,} | Return: {r['total_return_pct']:+.1f}% | "
                      f"CAGR: {r['cagr_pct']:+.1f}% | MaxDD: {r['max_drawdown_pct']:.1f}% | "
                      f"WinRate: {r['win_rate_pct']:.0f}% | Trades: {r['total_trades']}")
            else:
                print(f"  FAILED: no results")
        except Exception as e:
            print(f"  ERROR: {e}")

    # Sort and report
    results.sort(key=lambda x: x["cagr_pct"], reverse=True)

    print(f"\n\n{'='*60}")
    print("RESULTS RANKED BY CAGR")
    print(f"{'='*60}")
    print(f"{'Config':<55} {'Final':>10} {'CAGR':>7} {'MaxDD':>7} {'Win%':>5} {'Trd':>4} {'Freq':>10}")
    print("-" * 100)

    for r in results:
        marker = " <-- BEST" if r == results[0] else (" <-- WORST" if r == results[-1] else "")
        print(f"{r['config_name']:<55} {r['final_value']:>10,} {r['cagr_pct']:>+6.1f}% "
              f"{r['max_drawdown_pct']:>6.1f}% {r['win_rate_pct']:>4.0f}% {r['total_trades']:>4} "
              f"{r['rebal_freq']:>10}{marker}")

    # Save results (without full trade log to save space)
    save_results = []
    for r in results:
        sr = {k: v for k, v in r.items() if k not in ["trades", "equity"]}
        sr["trade_count"] = len(r["trades"])
        save_results.append(sr)

    with open("backtest_v3_results.json", "w") as f:
        json.dump(save_results, f, indent=2, default=str)

    # Generate text report
    report_lines = []
    report_lines.append("=" * 100)
    report_lines.append("SCANNER v9E BACKTEST v3 — REBALANCING FREQUENCY + NEW INDICATORS")
    report_lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    report_lines.append(f"Period: {START} - {END} | Capital: Rs {CAPITAL:,}")
    report_lines.append("=" * 100)

    report_lines.append(f"\nTotal configurations tested: {len(results)}")
    report_lines.append(f"Rebalancing frequencies: DAILY, BI-WEEKLY, MONTHLY")
    report_lines.append(f"Indicators added: MACD(12,26,9), ADX(14), RS vs NIFTY 50\n")

    report_lines.append(f"{'='*100}")
    report_lines.append("TOP 20 CONFIGURATIONS")
    report_lines.append(f"{'='*100}")
    report_lines.append(f"{'#':<4} {'Config':<50} {'Final':>10} {'CAGR':>7} {'MaxDD':>7} {'Win%':>5} {'Trd':>4}")
    report_lines.append("-" * 90)

    for i, r in enumerate(results[:20]):
        report_lines.append(f"{i+1:<4} {r['config_name']:<50} {r['final_value']:>10,} "
                           f"{r['cagr_pct']:>+6.1f}% {r['max_drawdown_pct']:>6.1f}% "
                           f"{r['win_rate_pct']:>4.0f}% {r['total_trades']:>4}")

    # Analyze by rebalancing frequency
    report_lines.append(f"\n{'='*100}")
    report_lines.append("ANALYSIS BY REBALANCING FREQUENCY")
    report_lines.append(f"{'='*100}")

    for freq in rebal_freqs:
        freq_results = [r for r in results if r["rebal_freq"] == freq]
        if freq_results:
            avg_cagr = np.mean([r["cagr_pct"] for r in freq_results])
            best_cagr = max(r["cagr_pct"] for r in freq_results)
            avg_dd = np.mean([r["max_drawdown_pct"] for r in freq_results])
            avg_trades = np.mean([r["total_trades"] for r in freq_results])
            report_lines.append(f"\n  {freq.upper()}:")
            report_lines.append(f"    Avg CAGR: {avg_cagr:+.1f}% | Best CAGR: {best_cagr:+.1f}%")
            report_lines.append(f"    Avg MaxDD: {avg_dd:.1f}% | Avg Trades: {avg_trades:.0f}")

    # Analyze by entry mode
    report_lines.append(f"\n{'='*100}")
    report_lines.append("ANALYSIS BY ENTRY MODE")
    report_lines.append(f"{'='*100}")

    for entry_name, _ in base_entry:
        entry_results = [r for r in results if entry_name in r["config_name"]]
        if entry_results:
            avg_cagr = np.mean([r["cagr_pct"] for r in entry_results])
            best_cagr = max(r["cagr_pct"] for r in entry_results)
            avg_dd = np.mean([r["max_drawdown_pct"] for r in entry_results])
            report_lines.append(f"\n  {entry_name}:")
            report_lines.append(f"    Avg CAGR: {avg_cagr:+.1f}% | Best CAGR: {best_cagr:+.1f}% | Avg MaxDD: {avg_dd:.1f}%")

    # Analyze by indicator combo
    report_lines.append(f"\n{'='*100}")
    report_lines.append("ANALYSIS BY INDICATOR COMBO")
    report_lines.append(f"{'='*100}")

    for ind_name, _, _, _, _ in indicator_combos:
        ind_results = [r for r in results if ind_name in r["config_name"]]
        if ind_results:
            avg_cagr = np.mean([r["cagr_pct"] for r in ind_results])
            best_cagr = max(r["cagr_pct"] for r in ind_results)
            report_lines.append(f"\n  {ind_name}:")
            report_lines.append(f"    Avg CAGR: {avg_cagr:+.1f}% | Best CAGR: {best_cagr:+.1f}%")

    # Analyze by stop type
    report_lines.append(f"\n{'='*100}")
    report_lines.append("ANALYSIS BY STOP TYPE")
    report_lines.append(f"{'='*100}")

    for stop in stops:
        stop_results = [r for r in results if r["config_params"].get("stop_type") == stop]
        if stop_results:
            avg_cagr = np.mean([r["cagr_pct"] for r in stop_results])
            best_cagr = max(r["cagr_pct"] for r in stop_results)
            avg_dd = np.mean([r["max_drawdown_pct"] for r in stop_results])
            report_lines.append(f"\n  {stop}:")
            report_lines.append(f"    Avg CAGR: {avg_cagr:+.1f}% | Best CAGR: {best_cagr:+.1f}% | Avg MaxDD: {avg_dd:.1f}%")

    # Best config details
    best = results[0]
    report_lines.append(f"\n{'='*100}")
    report_lines.append("BEST CONFIGURATION")
    report_lines.append(f"{'='*100}")
    report_lines.append(f"  Name: {best['config_name']}")
    report_lines.append(f"  Final Value: Rs {best['final_value']:,}")
    report_lines.append(f"  Total Return: {best['total_return_pct']:+.1f}%")
    report_lines.append(f"  CAGR: {best['cagr_pct']:+.1f}%")
    report_lines.append(f"  Max Drawdown: {best['max_drawdown_pct']:.1f}%")
    report_lines.append(f"  Win Rate: {best['win_rate_pct']:.1f}%")
    report_lines.append(f"  Avg Win: {best['avg_win_pct']:+.1f}%")
    report_lines.append(f"  Avg Loss: {best['avg_loss_pct']:+.1f}%")
    report_lines.append(f"  Total Trades: {best['total_trades']}")
    report_lines.append(f"  Rebalancing: {best['rebal_freq']}")
    report_lines.append(f"  Parameters: {json.dumps(best['config_params'], indent=4)}")

    # Worst config
    worst = results[-1]
    report_lines.append(f"\n{'='*100}")
    report_lines.append("WORST CONFIGURATION")
    report_lines.append(f"{'='*100}")
    report_lines.append(f"  Name: {worst['config_name']}")
    report_lines.append(f"  Final Value: Rs {worst['final_value']:,}")
    report_lines.append(f"  CAGR: {worst['cagr_pct']:+.1f}%")

    # Buy and hold comparison
    report_lines.append(f"\n{'='*100}")
    report_lines.append("BUY AND HOLD COMPARISON")
    report_lines.append(f"{'='*100}")

    for name in ["NIFTY 50", "NIFTY BANK", "NIFTY IT"]:
        if name in all_data and all_data[name] is not None:
            df = all_data[name]
            start_price = df["Close"].iloc[0]
            end_price = df["Close"].iloc[-1]
            bh_return = (end_price - start_price) / start_price * 100
            bh_years = len(df) / 252
            bh_cagr = ((end_price / start_price) ** (1/bh_years) - 1) * 100
            report_lines.append(f"  {name}: Return {bh_return:+.1f}% | CAGR {bh_cagr:+.1f}%")

    report_text = "\n".join(report_lines)

    with open("backtest_v3_report.txt", "w", encoding="utf-8") as f:
        f.write(report_text)

    print(f"\n\nReports saved:")
    print(f"  backtest_v3_results.json")
    print(f"  backtest_v3_report.txt")

    print(f"\n{report_text}")

if __name__ == "__main__":
    main()
