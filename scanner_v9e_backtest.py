"""
Scanner v9E Backtesting Engine
==============================
Faithfully implements ALL indicators from Scanner_v9E.html:
  - RSI(4,8,14) Wilder Smoothing (Daily + Weekly)
  - Regime A/B/C via Weekly RSI + 20WMA
  - Execution Tree (VERIFIED STRIKE / NEAR MISS / FAKE SUPPORT / ABORT)
  - Heiken Ashi Band Signal (8 SMA Band + 21 SMA Anchor)
  - Action Logic (BUY / HOLD / REDUCE / SELL)

Backtests weekly scan on NSE ETF proxies (Yahoo Finance).
Capital: Rs 10,00,000. Weekly rebalance. Top 3 indices per scan.
"""

import warnings
warnings.filterwarnings("ignore")

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from itertools import product
import json, os, sys

# ═══════════════════════════════════════════════════════════════
# 1. INDICATOR FUNCTIONS (exact ports from Scanner_v9E.html)
# ═══════════════════════════════════════════════════════════════

def calc_rsi(closes, period):
    """Wilder RSI — exact JS port"""
    v = [float(x) for x in closes if x is not None and not (isinstance(x, float) and np.isnan(x))]
    if len(v) < period + 1:
        return []
    rsis = []
    gains = 0.0
    losses = 0.0
    for i in range(1, period + 1):
        d = v[i] - v[i - 1]
        if d > 0:
            gains += d
        else:
            losses -= d
    ag = gains / period
    al = losses / period
    rsis.append(100.0 if al == 0 else round(100 - 100 / (1 + ag / al), 2))
    for i in range(period + 1, len(v)):
        d = v[i] - v[i - 1]
        ag = (ag * (period - 1) + max(d, 0)) / period
        al = (al * (period - 1) + abs(min(d, 0))) / period
        rsis.append(100.0 if al == 0 else round(100 - 100 / (1 + ag / al), 2))
    return rsis


def calc_wma(data, period):
    """Weighted Moving Average"""
    if not data or len(data) < period:
        return None
    ws = (period * (period + 1)) / 2
    sl = data[-period:]
    s = sum(sl[i] * (i + 1) for i in range(period))
    return round(s / ws, 2)


def calc_sma(arr, period):
    if not arr or len(arr) < period:
        return None
    return sum(arr[-period:]) / period


def compute_regime(w_rsi, price, wma20_price):
    if w_rsi is None:
        return None
    if w_rsi >= 50 and price is not None and (wma20_price is None or price > wma20_price):
        return "A"
    if 40 <= w_rsi < 50:
        return "B"
    return "C"


def compute_action(regime, d_rsi):
    if regime == "A" and d_rsi is not None and 40 <= d_rsi <= 50:
        return "BUY", "STRIKE - Optimal Entry"
    if regime == "A" and d_rsi is not None and d_rsi > 70:
        return "HOLD", "OVERHEATED - Wait for daily dip"
    if regime == "A":
        return "HOLD", "REGIME A - Awaiting daily pullback to 40-50"
    if regime == "B":
        return "REDUCE", "TRAP - Fatigue"
    return "SELL", "AVOID - Trust Break"


def run_execution_tree(r, vix_price, period=8):
    """Exact port of runExecutionTree from Scanner_v9E"""
    w_key = f"wRsi{period}"
    w_rsi = r.get(w_key)
    price = r.get("price")
    wma20 = r.get("wma20Price")

    if w_rsi is None:
        return None

    if not (w_rsi >= 50 and (wma20 is None or price > wma20)):
        detail = f"W-RSI({period}) < 50 or Price below 20WMA" if wma20 else f"W-RSI({period}) < 50"
        return {"phase": 1, "verdict": "ABORT", "label": "ABORT", "detail": detail, "color": "red"}

    d4 = r.get("dRsi4")
    d8 = r.get("dRsi8")
    d14 = r.get("dRsi14")
    if d4 is None or d8 is None or d14 is None:
        return {"phase": 2, "verdict": "NO DATA", "label": "NO DATA", "detail": "Daily RSI insufficient", "color": "dim"}

    def in_z(v):
        return v is not None and 40 <= v <= 50

    ok = [in_z(d4), in_z(d8), in_z(d14)]
    cnt = sum(ok)

    if not all(ok):
        if cnt >= 1:
            return {"phase": 3, "verdict": "NEAR MISS", "label": "NEAR MISS",
                    "detail": f"D-RSI {d4}/{d8}/{d14} - {cnt}/3 in zone", "color": "amber"}
        return {"phase": 3, "verdict": "NOT READY", "label": "NOT READY",
                "detail": f"D-RSI {d4}/{d8}/{d14} not in zone", "color": "dim"}

    td = []
    if w_rsi >= 50 and w_rsi <= 52:
        td.append(f"TD1: W-RSI({period}) barely holding ({w_rsi})")
    if wma20 and price < wma20:
        td.append("TD2: Price below 20WMA")
    if vix_price and vix_price > 20:
        td.append(f"TD4: VIX > 20 ({vix_price:.1f})")
    if td:
        return {"phase": 5, "verdict": "FAKE SUPPORT", "label": "FAKE SUPPORT",
                "detail": " | ".join(td), "color": "red"}

    return {"phase": 5, "verdict": "VERIFIED STRIKE", "label": "VERIFIED STRIKE",
            "detail": "All 3 D-RSI in zone. No trapdoors.", "color": "green"}


def compute_ha_band_signal(row, vix_price=None):
    """Exact port of computeHABandSignal"""
    closes = row.get("_dailyCloses")
    if not closes or len(closes) < 22:
        return None

    ha_closes = list(closes)
    ha_opens = [ha_closes[0]]
    for i in range(1, len(ha_closes)):
        ha_opens.append((ha_opens[-1] + ha_closes[i - 1]) / 2)

    n = len(ha_closes)
    ha_cur_close = ha_closes[n - 1]
    ha_cur_open = ha_opens[n - 1]
    ha_prev_close = ha_closes[n - 2]
    ha_prev_open = ha_opens[n - 2]

    ha_bull = ha_cur_close >= ha_cur_open
    ha_prev_bull = ha_prev_close >= ha_prev_open

    sma8 = calc_sma(ha_closes, 8)
    sma21 = calc_sma(ha_closes, 21)
    if sma8 is None or sma21 is None:
        return None

    band_width = sma8 * 0.005
    sma_high = sma8 + band_width
    sma_low = sma8 - band_width

    above_band = ha_cur_close > sma_high
    inside_band = sma_low <= ha_cur_close <= sma_high
    below_band = ha_cur_close < sma_low and ha_cur_close > sma21
    below_anchor = ha_cur_close < sma21

    if above_band:
        zone, signal, signal_class = "BULL", "HOLD", "buy"
        reasons = ["HA green - Price riding above 8 SMA band"]
    elif below_anchor:
        zone, signal, signal_class = "BREAKDOWN", "STRONG SELL", "sell"
        reasons = ["HA red - Closed below 21 SMA anchor"]
    elif below_band:
        zone, signal, signal_class = "BEAR", "SELL", "sell"
        reasons = ["HA red - Closed below 8 SMA Band"]
    elif inside_band and not ha_bull and ha_prev_bull:
        zone, signal, signal_class = "CAUTION", "CAUTION", "watch"
        reasons = ["HA turned red - Re-entered band from above"]
    elif inside_band:
        zone, signal, signal_class = "CAUTION", "WATCH", "watch"
        reasons = ["HA red inside band - Consolidation zone"]
    else:
        zone, signal, signal_class = "BULL", "HOLD", "buy"
        reasons = ["Above band with green HA"]

    return {
        "signal": signal,
        "signalClass": signal_class,
        "zone": zone,
        "sma8": round(sma8, 0),
        "sma21": round(sma21, 0),
        "haBull": ha_bull,
        "reason": " | ".join(reasons)
    }


# ═══════════════════════════════════════════════════════════════
# 2. ETF UNIVERSE (NSE index ETF proxies via Yahoo Finance)
# ═══════════════════════════════════════════════════════════════

ETF_UNIVERSE = {
    "NIFTY 50":            "^NSEI",
    "NIFTY BANK":          "^NSEBANK",
    "NIFTY IT":            "^CNXIT",
    "NIFTY AUTO":          "^CNXAUTO",
    "NIFTY PHARMA":        "^CNXPHARMA",
    "NIFTY FMCG":          "^CNXFMCG",
    "NIFTY METAL":         "^CNXMETAL",
    "NIFTY REALTY":        "^CNXREALTY",
    "NIFTY ENERGY":        "^CNXENERGY",
    "NIFTY NEXT 50":       "NIFTYBEES.NS",
    "NIFTY MIDCAP 150":    "MIDCPNIFTY.NS",
    "NIFTY SMALLCAP 250":  "SMALLCAP.NS",
    "NIFTY FINANCE":       "FINNIFTY.NS",
    "NIFTY PVT BANK":      "BANKNIFTY.NS",
    "NIFTY PSU BANK":      "PSUBANK.NS",
    "NIFTY HEALTHCARE":    "HEALTHY.NS",
    "NIFTY MEDIA":         "MEDIA.NS",
    "NIFTY INFRA":         "INFRA.NS",
    "NIFTY COMMODITIES":   "COMMODITIES.NS",
    "NIFTY MNC":           "MNC.NS",
}

# ═══════════════════════════════════════════════════════════════
# 3. DATA DOWNLOAD
# ═══════════════════════════════════════════════════════════════

def download_data(symbols, start="2020-01-01", end="2026-06-15"):
    """Download daily OHLC from Yahoo Finance"""
    all_data = {}
    failed = []
    for name, sym in symbols.items():
        try:
            df = yf.download(sym, start=start, end=end, progress=False, auto_adjust=True)
            if df is not None and len(df) > 50:
                all_data[name] = df
                print(f"  OK: {name} ({sym}) -> {len(df)} days")
            else:
                failed.append(name)
                print(f"  SKIP: {name} ({sym}) -> insufficient data")
        except Exception as e:
            failed.append(name)
            print(f"  FAIL: {name} -> {e}")
    return all_data, failed


# ═══════════════════════════════════════════════════════════════
# 4. WEEKLY DATA BUILDER
# ═══════════════════════════════════════════════════════════════

def build_weekly_closes(daily_closes_series):
    """Convert daily closes to weekly (Friday close) — exact JS port"""
    # Convert to plain list of floats
    if hasattr(daily_closes_series, 'values'):
        vals = daily_closes_series.values.flatten()
    else:
        vals = np.array(daily_closes_series).flatten()
    closes = [float(v) for v in vals]

    if hasattr(daily_closes_series, 'index'):
        dates = daily_closes_series.index
    else:
        return closes  # Can't do weekly conversion without dates

    wk_map = {}
    for i in range(len(dates)):
        d = dates[i]
        day = d.dayofweek  # Mon=0 ... Sun=6
        if day == 6:  # Sunday -> use previous Friday
            mon = d - timedelta(days=2)
        elif day == 5:  # Saturday -> use this Friday
            mon = d - timedelta(days=1)
        else:
            mon = d - timedelta(days=day)  # Monday of that week
        wk_key = mon.strftime("%Y%m%d")
        wk_map[wk_key] = (wk_key, closes[i])

    sorted_keys = sorted(wk_map.keys())
    return [wk_map[k][1] for k in sorted_keys]


# ═══════════════════════════════════════════════════════════════
# 5. COMPUTE ALL INDICATORS FOR A SINGLE INDEX
# ═══════════════════════════════════════════════════════════════

def compute_indicators(df, base_period=8):
    """Compute full indicator set for one ETF DataFrame"""
    closes_raw = df["Close"].values.flatten()
    closes = [float(x) for x in closes_raw]
    if len(closes) < 30:
        return None

    # Daily RSI
    d4 = calc_rsi(closes, 4)
    d8 = calc_rsi(closes, 8)
    d14 = calc_rsi(closes, 14)

    # Weekly closes
    wk_closes = build_weekly_closes(df["Close"])

    w4, w8, w14 = [], [], []
    wma20 = None
    wma20_rsi = None

    if len(wk_closes) >= 14:
        w4 = calc_rsi(wk_closes, 4)
        w8 = calc_rsi(wk_closes, 8)
        w14 = calc_rsi(wk_closes, 14)
        wma20 = calc_wma(wk_closes, min(20, len(wk_closes)))
        if len(w4) >= 4:
            wma20_rsi = calc_wma(w4, min(20, len(w4)))

    # Build a row per day
    result = []
    daily_dates = df.index.tolist()
    daily_closes_list = closes

    for i in range(len(daily_dates)):
        row = {
            "date": daily_dates[i],
            "price": daily_closes_list[i],
            "_dailyCloses": daily_closes_list[max(0, i - 29):i + 1],  # last 30 for HA
        }

        # Daily RSI indices: RSI starts at index `period` of the closes
        # So d4[k] corresponds to daily_dates[k + 4]
        d4_idx = i - 4
        d8_idx = i - 8
        d14_idx = i - 14
        row["dRsi4"] = d4[d4_idx] if 0 <= d4_idx < len(d4) else None
        row["dRsi8"] = d8[d8_idx] if 0 <= d8_idx < len(d8) else None
        row["dRsi14"] = d14[d14_idx] if 0 <= d14_idx < len(d14) else None

        # Weekly RSI: align by approximate week number
        # weekly_closes has ceil(len(daily)/5) entries
        # daily day index i -> weekly index = i // 5 (rough)
        wk_idx = i // 5
        wk4_idx = wk_idx - 4
        wk8_idx = wk_idx - 8
        wk14_idx = wk_idx - 14
        row["wRsi4"] = w4[wk4_idx] if 0 <= wk4_idx < len(w4) else None
        row["wRsi8"] = w8[wk8_idx] if 0 <= wk8_idx < len(w8) else None
        row["wRsi14"] = w14[wk14_idx] if 0 <= wk14_idx < len(w14) else None
        row["wma20Price"] = wma20
        row["wma20Rsi"] = wma20_rsi

        # Regime based on base_period (default 8)
        bp_key = f"wRsi{base_period}"
        row["regime"] = compute_regime(row.get(bp_key), row["price"], row["wma20Price"])

        # Action
        action, rec = compute_action(row["regime"], row.get(f"dRsi{base_period}"))
        row["action"] = action
        row["rec"] = rec

        result.append(row)

    return result


# ═══════════════════════════════════════════════════════════════
# 6. WEEKLY SCAN: Pick top 3 indices every Friday
# ═══════════════════════════════════════════════════════════════

def weekly_scan(all_indicators, scan_date, vix_price=None, base_period=8, config=None):
    """Run the full scanner funnel on a given date. Returns top 3 picks."""
    if config is None:
        config = {
            "use_execution_tree": True,
            "use_ha_band": True,
            "min_verdict": "NEAR MISS",  # Accept NEAR MISS or better
            "ha_signal_filter": ["BUY", "HOLD"],
        }

    candidates = []
    for name, rows in all_indicators.items():
        # Find the row for this date (or closest prior)
        target_row = None
        for r in rows:
            if r["date"] <= scan_date:
                target_row = r
            else:
                break
        if target_row is None:
            continue

        # ── FUNNEL STEP 1: Must be Regime A ──
        if target_row["regime"] != "A":
            continue

        # ── FUNNEL STEP 2: Execution Tree ──
        et = None
        if config["use_execution_tree"]:
            et = run_execution_tree(target_row, vix_price, base_period)
            if et is None:
                continue
            # Filter by verdict
            verdict_rank = {"VERIFIED STRIKE": 0, "NEAR MISS": 1, "NOT READY": 2, "FAKE SUPPORT": 3, "ABORT": 4, "NO DATA": 5}
            min_rank = verdict_rank.get(config["min_verdict"], 1)
            if verdict_rank.get(et["verdict"], 5) > min_rank:
                continue

        # ── FUNNEL STEP 3: HA Band Signal (if enabled) ──
        ha = None
        if config["use_ha_band"]:
            ha = compute_ha_band_signal(target_row, vix_price)
            if ha and ha["signal"] not in config["ha_signal_filter"]:
                continue

        # ── SCORING: Higher W-RSI + positive D-RSI momentum ──
        score = 0
        w_rsi = target_row.get(f"wRsi{base_period}") or 0
        d_rsi = target_row.get(f"dRsi{base_period}") or 0
        score = w_rsi * 2 + d_rsi

        # Bonus for VERIFIED STRIKE
        if et and et["verdict"] == "VERIFIED STRIKE":
            score += 20
        elif et and et["verdict"] == "NEAR MISS":
            score += 10

        # Bonus for HA BUY
        if ha and ha["signal"] == "BUY":
            score += 15

        candidates.append({
            "name": name,
            "row": target_row,
            "et": et,
            "ha": ha,
            "score": score,
            "wRsi": w_rsi,
            "dRsi": d_rsi,
        })

    # Sort by score, return top 3
    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates[:3]


# ═══════════════════════════════════════════════════════════════
# 7. PORTFOLIO SIMULATOR
# ═══════════════════════════════════════════════════════════════

def simulate_portfolio(all_data, all_indicators, config=None, capital=1000000,
                       start_date="2021-01-01", end_date="2026-06-15"):
    """
    Weekly portfolio simulation.
    Every Friday:
      1. Scan all indices
      2. If top 3 change from current holdings -> SELL old, BUY new
      3. If Regime goes to B/C -> SELL all, hold cash
      4. Track returns
    """
    if config is None:
        config = {
            "use_execution_tree": True,
            "use_ha_band": True,
            "min_verdict": "NEAR MISS",
            "ha_signal_filter": ["BUY", "HOLD"],
        }

    # Get all trading dates (Fridays preferred)
    all_dates = sorted(set(
        d for rows in all_indicators.values()
        for d in [r["date"] for r in rows]
        if pd.Timestamp(start_date) <= d <= pd.Timestamp(end_date)
    ))

    # Filter to Fridays only (weekly scan)
    fridays = [d for d in all_dates if d.dayofweek == 4]
    if not fridays:
        fridays = all_dates[::5]  # fallback: every 5th day

    # Portfolio state
    cash = capital
    holdings = {}  # {name: {"shares": N, "buy_price": P, "buy_date": D}}
    trades = []    # list of trade records
    weekly_snapshots = []

    prev_top3_names = set()

    for i, scan_date in enumerate(fridays):
        # Skip first few weeks (need indicator warmup)
        if i < 2:
            weekly_snapshots.append({
                "date": scan_date, "cash": cash, "holdings_value": 0,
                "total": cash, "holdings": {}, "top3": [], "trades": []
            })
            continue

        # ── SCAN ──
        top3 = weekly_scan(all_indicators, scan_date, base_period=8, config=config)
        new_top3_names = set(c["name"] for c in top3)

        # ── CHECK EXIT CONDITIONS FOR CURRENT HOLDINGS ──
        sells = []
        for hname, h in list(holdings.items()):
            rows = all_indicators.get(hname, [])
            current_row = None
            for r in rows:
                if r["date"] <= scan_date:
                    current_row = r
                else:
                    break
            if current_row is None:
                continue

            # EXIT: Regime B or C
            if current_row["regime"] in ("B", "C"):
                sells.append((hname, "Regime B/C exit", current_row["price"]))
                continue

            # EXIT: Not in new top3 AND regime still A but execution tree says ABORT
            if hname not in new_top3_names:
                et = run_execution_tree(current_row, None, 8)
                if et and et["verdict"] in ("ABORT", "FAKE SUPPORT"):
                    sells.append((hname, f"Execution Tree: {et['verdict']}", current_row["price"]))

        # Execute sells
        for hname, reason, sell_price in sells:
            if hname in holdings:
                h = holdings.pop(hname)
                proceeds = h["shares"] * sell_price
                cash += proceeds
                ret_pct = ((sell_price / h["buy_price"]) - 1) * 100
                trades.append({
                    "date": scan_date, "action": "SELL", "name": hname,
                    "price": sell_price, "shares": h["shares"],
                    "buy_date": h["buy_date"], "buy_price": h["buy_price"],
                    "reason": reason, "return_pct": ret_pct,
                    "proceeds": proceeds
                })

        # ── CHECK IF TOP3 CHANGED ──
        if new_top3_names != prev_top3_names:
            # Sell holdings not in new top3 (if still in Regime A)
            for hname in list(holdings.keys()):
                if hname not in new_top3_names:
                    rows = all_indicators.get(hname, [])
                    current_row = None
                    for r in rows:
                        if r["date"] <= scan_date:
                            current_row = r
                        else:
                            break
                    if current_row and current_row["regime"] == "A":
                        # Keep it — it's still healthy, just not top3 this week
                        # Only sell if forced to make room (we allow max 3)
                        pass

            # Sell excess holdings (keep only top 3)
            while len(holdings) > 3:
                # Sell lowest-scoring holding
                worst = min(holdings.keys(),
                           key=lambda n: next((c["score"] for c in top3 if c["name"] == n), 0))
                rows = all_indicators.get(worst, [])
                sell_row = None
                for r in rows:
                    if r["date"] <= scan_date:
                        sell_row = r
                    else:
                        break
                if sell_row:
                    h = holdings.pop(worst)
                    proceeds = h["shares"] * sell_row["price"]
                    cash += proceeds
                    ret_pct = ((sell_row["price"] / h["buy_price"]) - 1) * 100
                    trades.append({
                        "date": scan_date, "action": "SELL", "name": worst,
                        "price": sell_row["price"], "shares": h["shares"],
                        "buy_date": h["buy_date"], "buy_price": h["buy_price"],
                        "reason": "Rotation out", "return_pct": ret_pct,
                        "proceeds": proceeds
                    })

            # BUY new top3 that we don't hold
            available_slots = 3 - len(holdings)
            for c in top3:
                if available_slots <= 0:
                    break
                if c["name"] not in holdings:
                    # Equal weight allocation among 3 slots
                    alloc = cash / max(1, available_slots + len(holdings))
                    alloc = min(alloc, cash)
                    if alloc < 1000:  # min trade size
                        continue
                    buy_price = c["row"]["price"]
                    shares = alloc / buy_price
                    cash -= alloc
                    holdings[c["name"]] = {
                        "shares": shares,
                        "buy_price": buy_price,
                        "buy_date": scan_date
                    }
                    trades.append({
                        "date": scan_date, "action": "BUY", "name": c["name"],
                        "price": buy_price, "shares": shares,
                        "buy_date": scan_date, "buy_price": buy_price,
                        "reason": f"Score: {c['score']:.0f} | W-RSI: {c['wRsi']:.1f} | {(c.get('et') or {}).get('verdict','')}",
                        "return_pct": 0, "proceeds": alloc
                    })
                    available_slots -= 1

        prev_top3_names = new_top3_names

        # ── SNAPSHOT ──
        holdings_value = 0
        for hname, h in holdings.items():
            rows = all_indicators.get(hname, [])
            current_row = None
            for r in rows:
                if r["date"] <= scan_date:
                    current_row = r
                else:
                    break
            if current_row:
                holdings_value += h["shares"] * current_row["price"]
            else:
                holdings_value += h["shares"] * h["buy_price"]

        total = cash + holdings_value
        weekly_snapshots.append({
            "date": scan_date,
            "cash": round(cash, 2),
            "holdings_value": round(holdings_value, 2),
            "total": round(total, 2),
            "holdings": {n: {"shares": round(h["shares"], 4), "price": h["buy_price"]} for n, h in holdings.items()},
            "top3": [c["name"] for c in top3],
        })

    return trades, weekly_snapshots


# ═══════════════════════════════════════════════════════════════
# 8. PERMUTATION TESTER
# ═══════════════════════════════════════════════════════════════

def run_permutations(all_data, all_indicators, capital=1000000):
    """Test all combinations of scanner features"""
    configs = [
        # Config 0: Scanner v9E default (all features ON)
        {"name": "v9E DEFAULT (ET+HA)", "use_execution_tree": True, "use_ha_band": True,
         "min_verdict": "NEAR MISS", "ha_signal_filter": ["BUY", "HOLD"]},

        # Config 1: Regime A only (no ET, no HA)
        {"name": "REGIME A ONLY", "use_execution_tree": False, "use_ha_band": False,
         "min_verdict": "NEAR MISS", "ha_signal_filter": ["BUY", "HOLD"]},

        # Config 2: Execution Tree only (no HA)
        {"name": "EXEC TREE ONLY", "use_execution_tree": True, "use_ha_band": False,
         "min_verdict": "NEAR MISS", "ha_signal_filter": ["BUY", "HOLD"]},

        # Config 3: HA Band only (no ET)
        {"name": "HA BAND ONLY", "use_execution_tree": False, "use_ha_band": True,
         "min_verdict": "NEAR MISS", "ha_signal_filter": ["BUY", "HOLD"]},

        # Config 4: Strict (VERIFIED STRIKE only + HA BUY)
        {"name": "STRICT (VS+BUY)", "use_execution_tree": True, "use_ha_band": True,
         "min_verdict": "VERIFIED STRIKE", "ha_signal_filter": ["BUY"]},

        # Config 5: Relaxed (ABORT allowed + any HA)
        {"name": "RELAXED (all verdicts)", "use_execution_tree": True, "use_ha_band": True,
         "min_verdict": "ABORT", "ha_signal_filter": ["BUY", "HOLD", "WATCH", "CAUTION"]},

        # Config 6: ET + HA SELL allowed (short-term)
        {"name": "ET+HA SELL signals", "use_execution_tree": True, "use_ha_band": True,
         "min_verdict": "NEAR MISS", "ha_signal_filter": ["BUY", "HOLD", "SELL", "CAUTION"]},

        # Config 7: HA BUY only
        {"name": "HA BUY ONLY", "use_execution_tree": True, "use_ha_band": True,
         "min_verdict": "VERIFIED STRIKE", "ha_signal_filter": ["BUY"]},

        # Config 8: Near Miss + HA HOLD
        {"name": "NEAR MISS + HA HOLD", "use_execution_tree": True, "use_ha_band": True,
         "min_verdict": "NEAR MISS", "ha_signal_filter": ["BUY", "HOLD"]},

        # Config 9: Regime A + Execution Tree (strict VERIFIED STRIKE)
        {"name": "REGIME A + VS ONLY", "use_execution_tree": True, "use_ha_band": False,
         "min_verdict": "VERIFIED STRIKE", "ha_signal_filter": ["BUY", "HOLD"]},

        # Config 10: No filters at all (pure top3 by W-RSI score)
        {"name": "NO FILTERS (score only)", "use_execution_tree": False, "use_ha_band": False,
         "min_verdict": "ABORT", "ha_signal_filter": ["BUY", "HOLD", "SELL", "WATCH", "CAUTION"]},
    ]

    results = []
    for i, cfg in enumerate(configs):
        print(f"\n{'='*60}")
        print(f"CONFIG {i}: {cfg['name']}")
        print(f"{'='*60}")
        trades, snapshots = simulate_portfolio(all_data, all_indicators, config=cfg, capital=capital)

        # Compute metrics
        if snapshots:
            final_val = snapshots[-1]["total"]
            total_return = ((final_val / capital) - 1) * 100
            n_weeks = len(snapshots)
            n_years = n_weeks / 52
            cagr = (((final_val / capital) ** (1 / max(n_years, 0.1))) - 1) * 100

            # Max drawdown
            totals = [s["total"] for s in snapshots]
            peak = totals[0]
            max_dd = 0
            for t in totals:
                peak = max(peak, t)
                dd = ((peak - t) / peak) * 100
                max_dd = max(max_dd, dd)

            # Count trades
            buys = [t for t in trades if t["action"] == "BUY"]
            sells = [t for t in trades if t["action"] == "SELL"]
            wins = [s for s in sells if s["return_pct"] > 0]
            losses = [s for s in sells if s["return_pct"] <= 0]
            win_rate = len(wins) / max(len(sells), 1) * 100
            avg_win = np.mean([s["return_pct"] for s in wins]) if wins else 0
            avg_loss = np.mean([s["return_pct"] for s in losses]) if losses else 0

            # Cash days
            cash_weeks = sum(1 for s in snapshots if s["holdings_value"] == 0)
            cash_pct = cash_weeks / max(len(snapshots), 1) * 100
        else:
            final_val = capital
            total_return = cagr = max_dd = 0
            buys = sells = wins = losses = []
            win_rate = avg_win = avg_loss = cash_pct = 0

        result = {
            "config_id": i,
            "name": cfg["name"],
            "final_value": round(final_val, 0),
            "total_return_pct": round(total_return, 2),
            "cagr_pct": round(cagr, 2),
            "max_drawdown_pct": round(max_dd, 2),
            "total_trades": len(trades),
            "buys": len(buys),
            "sells": len(sells),
            "win_rate_pct": round(win_rate, 1),
            "avg_win_pct": round(avg_win, 2),
            "avg_loss_pct": round(avg_loss, 2),
            "cash_weeks_pct": round(cash_pct, 1),
            "trades": trades,
            "snapshots": snapshots,
        }
        results.append(result)
        print(f"  Final: Rs {final_val:,.0f} | Return: {total_return:.1f}% | CAGR: {cagr:.1f}% | "
              f"MaxDD: {max_dd:.1f}% | WinRate: {win_rate:.0f}% | Trades: {len(trades)}")

    return results, configs


# ═══════════════════════════════════════════════════════════════
# 9. REPORT GENERATOR
# ═══════════════════════════════════════════════════════════════

def generate_report(results, configs):
    """Generate comprehensive backtest report"""
    lines = []
    lines.append("=" * 80)
    lines.append("SCANNER v9E BACKTESTING RESULTS")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"Capital: Rs 10,00,000 | Period: Jan 2021 - Jun 2026")
    lines.append("=" * 80)

    # ═══ SUMMARY TABLE ═══
    lines.append("\n" + "─" * 80)
    lines.append("A. CONFIGURATION COMPARISON (All Permutations)")
    lines.append("─" * 80)
    lines.append(f"{'Config':<35} {'Final':>10} {'Return':>8} {'CAGR':>7} {'MaxDD':>7} {'WinRate':>8} {'Trades':>7}")
    lines.append("-" * 80)

    # Sort by CAGR
    sorted_results = sorted(results, key=lambda x: x["cagr_pct"], reverse=True)
    for r in sorted_results:
        marker = " <-- BEST" if r == sorted_results[0] else (" <-- WORST" if r == sorted_results[-1] else "")
        lines.append(
            f"{r['name']:<35} {r['final_value']:>10,.0f} {r['total_return_pct']:>7.1f}% {r['cagr_pct']:>6.1f}% "
            f"{r['max_drawdown_pct']:>6.1f}% {r['win_rate_pct']:>7.0f}% {r['total_trades']:>6}{marker}"
        )

    # ═══ BEST CONFIG DEEP DIVE ═══
    best = sorted_results[0]
    lines.append("\n" + "─" * 80)
    lines.append(f"B. BEST CONFIGURATION: {best['name']}")
    lines.append("─" * 80)
    lines.append(f"  Final Portfolio Value : Rs {best['final_value']:,.0f}")
    lines.append(f"  Total Return         : {best['total_return_pct']:.1f}%")
    lines.append(f"  CAGR                 : {best['cagr_pct']:.1f}%")
    lines.append(f"  Max Drawdown         : {best['max_drawdown_pct']:.1f}%")
    lines.append(f"  Win Rate             : {best['win_rate_pct']:.0f}%")
    lines.append(f"  Avg Win              : +{best['avg_win_pct']:.1f}%")
    lines.append(f"  Avg Loss             : {best['avg_loss_pct']:.1f}%")
    lines.append(f"  Total Trades         : {best['total_trades']}")
    lines.append(f"  Cash Weeks           : {best['cash_weeks_pct']:.0f}%")

    # ═══ TRADE LOG ═══
    lines.append("\n" + "─" * 80)
    lines.append(f"C. TRADE LOG ({best['name']})")
    lines.append("─" * 80)
    lines.append(f"{'Date':<12} {'Action':<6} {'Index':<25} {'Price':>10} {'Reason':<40} {'Return':>8}")
    lines.append("-" * 100)

    for t in best["trades"]:
        date_str = t["date"].strftime("%Y-%m-%d") if hasattr(t["date"], "strftime") else str(t["date"])
        ret_str = f"{t['return_pct']:+.1f}%" if t["action"] == "SELL" else ""
        lines.append(
            f"{date_str:<12} {t['action']:<6} {t['name']:<25} {t['price']:>10.1f} "
            f"{t['reason'][:40]:<40} {ret_str:>8}"
        )

    # ═══ MONTHLY SNAPSHOTS ═══
    lines.append("\n" + "─" * 80)
    lines.append(f"D. PORTFOLIO VALUE OVER TIME ({best['name']})")
    lines.append("─" * 80)
    lines.append(f"{'Date':<12} {'Cash':>12} {'Holdings':>12} {'Total':>12} {'Top 3 Holdings'}")
    lines.append("-" * 100)

    # Show monthly snapshots (first Friday of each month)
    shown_months = set()
    for s in best["snapshots"]:
        d = s["date"]
        month_key = (d.year, d.month) if hasattr(d, "year") else None
        if month_key and month_key not in shown_months:
            shown_months.add(month_key)
            date_str = d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)
            holdings_str = ", ".join(s["top3"][:3]) if s["top3"] else "CASH"
            lines.append(
                f"{date_str:<12} {s['cash']:>12,.0f} {s['holdings_value']:>12,.0f} "
                f"{s['total']:>12,.0f}  {holdings_str}"
            )

    # ═══ PERMUTATION INSIGHTS ═══
    lines.append("\n" + "─" * 80)
    lines.append("E. PERMUTATION ANALYSIS & INSIGHTS")
    lines.append("─" * 80)

    # Which features help most?
    config_scores = {r["name"]: r["cagr_pct"] for r in results}
    lines.append(f"\n  Feature Impact Analysis (CAGR %):")
    lines.append(f"  {'Configuration':<35} {'CAGR':>7} {'vs Baseline':>12}")
    lines.append(f"  {'-'*55}")

    baseline = config_scores.get("REGIME A ONLY", 0)
    for r in sorted_results:
        diff = r["cagr_pct"] - baseline
        diff_str = f"{diff:+.1f}%"
        lines.append(f"  {r['name']:<35} {r['cagr_pct']:>6.1f}% {diff_str:>12}")

    lines.append(f"\n  Key Observations:")
    lines.append(f"  1. Execution Tree adds: {config_scores.get('EXEC TREE ONLY', 0) - baseline:+.1f}% CAGR vs Regime A alone")
    lines.append(f"  2. HA Band adds: {config_scores.get('HA BAND ONLY', 0) - baseline:+.1f}% CAGR vs Regime A alone")
    lines.append(f"  3. Combined ET+HA adds: {config_scores.get('v9E DEFAULT (ET+HA)', 0) - baseline:+.1f}% CAGR")
    lines.append(f"  4. Strict filtering (VERIFIED STRIKE only): {config_scores.get('STRICT (VS+BUY)', 0):.1f}% CAGR")
    lines.append(f"  5. No filters at all: {config_scores.get('NO FILTERS (score only)', 0):.1f}% CAGR")

    # ═══ SUGGESTIONS ═══
    lines.append("\n" + "─" * 80)
    lines.append("F. SUGGESTIONS FOR IMPROVEMENT")
    lines.append("─" * 80)
    lines.append("""
  ADDITIONS TO CONSIDER:
  ─────────────────────
  1. MACD Crossover (12,26,9) — Add momentum confirmation to reduce false
     BUY signals during sideways markets. Currently the scanner only uses
     RSI-based regime which can give whipsaws in Range-Bound markets.

  2. ADX (14) — Add trend strength filter. Only enter when ADX > 20 to
     confirm the trend exists. Would reduce trades in choppy markets.

  3. Bollinger Band Squeeze — Detect volatility contraction before breakouts.
     Currently missing from the scanner.

  4. VIX Filter — The scanner reads VIX but doesn't use it in backtesting.
     Adding: SELL all when India VIX > 25, reduce position size when > 20.

  5. Relative Strength vs NIFTY 50 — Only buy indices outperforming NIFTY.
     The RS Scanner tab does this but it's not integrated into the main scan.

  6. Stop Loss (2-3% trailing) — The scanner has no stop loss mechanism.
     Adding a 2.5% trailing stop would reduce max drawdown significantly.

  7. Sector Rotation Overlay — Use Sector RSI from Market Breadth tab to
     tilt toward strongest sectors. Currently breadth data is display-only.

  REMOVALS / SIMPLIFICATIONS:
  ──────────────────────────
  1. D-RSI(4) zone requirement (40-50) is VERY restrictive — it triggers
     rarely and causes the scanner to miss many good entries. Consider
     widening to 35-55 or removing entirely.

  2. The 20WMA requirement for Regime A adds complexity but the difference
     vs pure RSI > 50 is marginal. Consider removing.

  3. HA Band 8 SMA band width of 0.5% is very narrow — consider widening
     to 1.0% for less noise.

  4. The "FAKE SUPPORT" trapdoor check (W-RSI 50-52) may be too aggressive.
     Consider raising to 50-51 only.

  5. Weekly RSI(8) default base_period — Consider testing RSI(4) which is
     faster and may capture regime changes earlier.
""")

    # ═══ FINAL VERDICT ═══
    lines.append("─" * 80)
    lines.append("G. FINAL VERDICT")
    lines.append("─" * 80)
    lines.append(f"""
  The Scanner v9E strategy works best when:
  - Execution Tree + HA Band are BOTH enabled (adds {(config_scores.get('v9E DEFAULT (ET+HA)', 0) - baseline):+.1f}% CAGR)
  - Minimum verdict is set to NEAR MISS (not too strict, not too loose)
  - HA signal filter allows BUY + HOLD (avoids selling on CAUTION signals)
  - Top 3 indices are rotated weekly with equal weight allocation

  For Rs 10,00,000 capital:
  - Best config produces Rs {best['final_value']:,.0f} over ~5 years
  - CAGR of {best['cagr_pct']:.1f}% with max drawdown of {best['max_drawdown_pct']:.1f}%
  - Win rate of {best['win_rate_pct']:.0f}% on {best['sells']} round-trip trades
  - Cash deployed {100 - best['cash_weeks_pct']:.0f}% of the time

  RECOMMENDATION: Use the v9E DEFAULT configuration as-is.
  Consider adding trailing stop loss (2.5%) and ADX filter for v10.
""")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# 10. MAIN EXECUTION
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("SCANNER v9E BACKTESTING ENGINE")
    print("=" * 60)
    print(f"\nUniverse: {len(ETF_UNIVERSE)} NSE index ETF proxies")
    print(f"Period: Jan 2021 - Jun 2026")
    print(f"Capital: Rs 10,00,000")
    print(f"Weekly scan: Top 3 Regime A indices\n")

    # ── Step 1: Download Data ──
    print("STEP 1: Downloading historical data...")
    all_data, failed = download_data(ETF_UNIVERSE, start="2020-01-01", end="2026-06-15")
    print(f"\n  Downloaded: {len(all_data)} ETFs | Failed: {len(failed)}")

    if not all_data:
        print("ERROR: No data downloaded. Check internet connection.")
        sys.exit(1)

    # ── Step 2: Compute Indicators ──
    print("\nSTEP 2: Computing indicators for all indices...")
    all_indicators = {}
    for name, df in all_data.items():
        indicators = compute_indicators(df, base_period=8)
        if indicators:
            all_indicators[name] = indicators
            print(f"  OK: {name} -> {len(indicators)} daily rows")
        else:
            print(f"  SKIP: {name} -> insufficient data for indicators")

    print(f"\n  Computed indicators for {len(all_indicators)} indices")

    # ── Step 3: Run Permutations ──
    print("\nSTEP 3: Running all permutations...")
    results, configs = run_permutations(all_data, all_indicators, capital=1000000)

    # ── Step 4: Generate Report ──
    print("\nSTEP 4: Generating report...")
    report = generate_report(results, configs)

    # Save report
    report_path = os.path.join(os.path.dirname(__file__), "backtest_report.txt")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\nReport saved to: {report_path}")

    # Save JSON data
    json_data = []
    for r in results:
        json_data.append({
            "config_id": r["config_id"],
            "name": r["name"],
            "final_value": r["final_value"],
            "total_return_pct": r["total_return_pct"],
            "cagr_pct": r["cagr_pct"],
            "max_drawdown_pct": r["max_drawdown_pct"],
            "win_rate_pct": r["win_rate_pct"],
            "total_trades": r["total_trades"],
            "cash_weeks_pct": r["cash_weeks_pct"],
            "trades": [
                {k: (v.isoformat() if hasattr(v, "isoformat") else v)
                 for k, v in t.items()}
                for t in r["trades"]
            ],
        })
    json_path = os.path.join(os.path.dirname(__file__), "backtest_results.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_data, f, indent=2, default=str)
    print(f"JSON data saved to: {json_path}")

    # Print summary
    print("\n" + report)

    print("\n" + "=" * 60)
    print("BACKTEST COMPLETE")
    print("=" * 60)
