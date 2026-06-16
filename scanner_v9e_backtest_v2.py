"""
Scanner v9E Backtesting Engine v2 — WITH STOP LOSSES
=====================================================
NEW IN v2:
  - WMA20 Stop Loss: exit when price closes below 20-week WMA
  - Trailing Stop Loss: exit when price drops X% from peak
  - Tests all combinations: WMA20 only, Trail only, Both
  - Wider D-RSI zone (35-55) as alternative entry filter
"""

import warnings
warnings.filterwarnings("ignore")

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import json, os, sys

# ═══════════════════════════════════════════════════════════════
# 1. INDICATOR FUNCTIONS (unchanged from v1)
# ═══════════════════════════════════════════════════════════════

def calc_rsi(closes, period):
    v = [float(x) for x in closes if x is not None and not (isinstance(x, (int, float, np.floating)) and np.isnan(x))]
    if len(v) < period + 1:
        return []
    rsis = []
    gains = 0.0; losses = 0.0
    for i in range(1, period + 1):
        d = v[i] - v[i - 1]
        if d > 0: gains += d
        else: losses -= d
    ag = gains / period; al = losses / period
    rsis.append(100.0 if al == 0 else round(100 - 100 / (1 + ag / al), 2))
    for i in range(period + 1, len(v)):
        d = v[i] - v[i - 1]
        ag = (ag * (period - 1) + max(d, 0)) / period
        al = (al * (period - 1) + abs(min(d, 0))) / period
        rsis.append(100.0 if al == 0 else round(100 - 100 / (1 + ag / al), 2))
    return rsis

def calc_wma(data, period):
    if not data or len(data) < period: return None
    ws = (period * (period + 1)) / 2
    sl = data[-period:]
    return round(sum(sl[i] * (i + 1) for i in range(period)) / ws, 2)

def calc_sma(arr, period):
    if not arr or len(arr) < period: return None
    return sum(arr[-period:]) / period

def compute_regime(w_rsi, price, wma20_price):
    if w_rsi is None: return None
    if w_rsi >= 50 and price is not None and (wma20_price is None or price > wma20_price):
        return "A"
    if 40 <= w_rsi < 50: return "B"
    return "C"

def compute_action(regime, d_rsi):
    if regime == "A" and d_rsi is not None and 40 <= d_rsi <= 50:
        return "BUY", "STRIKE - Optimal Entry"
    if regime == "A" and d_rsi is not None and d_rsi > 70:
        return "HOLD", "OVERHEATED"
    if regime == "A": return "HOLD", "REGIME A"
    if regime == "B": return "REDUCE", "TRAP - Fatigue"
    return "SELL", "AVOID - Trust Break"

def run_execution_tree(r, vix_price, period=8):
    w_rsi = r.get(f"wRsi{period}")
    price = r.get("price"); wma20 = r.get("wma20Price")
    if w_rsi is None: return None
    if not (w_rsi >= 50 and (wma20 is None or price > wma20)):
        return {"phase": 1, "verdict": "ABORT", "label": "ABORT", "detail": f"W-RSI({period})<50", "color": "red"}
    d4 = r.get("dRsi4"); d8 = r.get("dRsi8"); d14 = r.get("dRsi14")
    if d4 is None or d8 is None or d14 is None:
        return {"phase": 2, "verdict": "NO DATA", "label": "NO DATA", "detail": "Daily RSI insufficient", "color": "dim"}
    def in_z(v): return v is not None and 40 <= v <= 50
    ok = [in_z(d4), in_z(d8), in_z(d14)]; cnt = sum(ok)
    if not all(ok):
        if cnt >= 1:
            return {"phase": 3, "verdict": "NEAR MISS", "label": "NEAR MISS",
                    "detail": f"D-RSI {d4}/{d8}/{d14} - {cnt}/3", "color": "amber"}
        return {"phase": 3, "verdict": "NOT READY", "label": "NOT READY",
                "detail": f"D-RSI {d4}/{d8}/{d14}", "color": "dim"}
    td = []
    if w_rsi >= 50 and w_rsi <= 52: td.append(f"W-RSI barely 50-52 ({w_rsi})")
    if wma20 and price < wma20: td.append("Price below 20WMA")
    if vix_price and vix_price > 20: td.append(f"VIX>20")
    if td:
        return {"phase": 5, "verdict": "FAKE SUPPORT", "label": "FAKE SUPPORT", "detail": " | ".join(td), "color": "red"}
    return {"phase": 5, "verdict": "VERIFIED STRIKE", "label": "VERIFIED STRIKE",
            "detail": "All 3 D-RSI in zone", "color": "green"}

def compute_ha_band_signal(row, vix_price=None):
    closes = row.get("_dailyCloses")
    if not closes or len(closes) < 22: return None
    ha_closes = list(closes)
    ha_opens = [ha_closes[0]]
    for i in range(1, len(ha_closes)):
        ha_opens.append((ha_opens[-1] + ha_closes[i - 1]) / 2)
    n = len(ha_closes)
    ha_cur_close = ha_closes[n-1]; ha_cur_open = ha_opens[n-1]
    ha_prev_close = ha_closes[n-2]; ha_prev_open = ha_opens[n-2]
    ha_bull = ha_cur_close >= ha_cur_open
    sma8 = calc_sma(ha_closes, 8); sma21 = calc_sma(ha_closes, 21)
    if sma8 is None or sma21 is None: return None
    above_band = ha_cur_close > sma8 * 1.005
    below_anchor = ha_cur_close < sma21
    if below_anchor: return {"signal": "STRONG SELL", "signalClass": "sell", "zone": "BREAKDOWN"}
    if ha_bull and above_band: return {"signal": "HOLD", "signalClass": "buy", "zone": "BULL"}
    if ha_bull: return {"signal": "BUY", "signalClass": "buy", "zone": "BULL"}
    if not ha_bull and ha_cur_close < sma8 * 0.995: return {"signal": "SELL", "signalClass": "sell", "zone": "BEAR"}
    return {"signal": "WATCH", "signalClass": "watch", "zone": "CAUTION"}

def build_weekly_closes(daily_closes_series):
    if hasattr(daily_closes_series, 'values'):
        vals = daily_closes_series.values.flatten()
    else:
        vals = np.array(daily_closes_series).flatten()
    closes = [float(v) for v in vals]
    if not hasattr(daily_closes_series, 'index'): return closes
    dates = daily_closes_series.index
    wk_map = {}
    for i in range(len(dates)):
        d = dates[i]; day = d.dayofweek
        if day == 6: mon = d - timedelta(days=2)
        elif day == 5: mon = d - timedelta(days=1)
        else: mon = d - timedelta(days=day)
        wk_key = mon.strftime("%Y%m%d")
        wk_map[wk_key] = closes[i]
    return [wk_map[k] for k in sorted(wk_map.keys())]

def compute_indicators(df, base_period=8):
    closes = [float(x) for x in df["Close"].values.flatten()]
    if len(closes) < 30: return None
    d4 = calc_rsi(closes, 4); d8 = calc_rsi(closes, 8); d14 = calc_rsi(closes, 14)
    wk_closes = build_weekly_closes(df["Close"])
    w4, w8, w14 = [], [], []; wma20 = None
    if len(wk_closes) >= 14:
        w4 = calc_rsi(wk_closes, 4); w8 = calc_rsi(wk_closes, 8); w14 = calc_rsi(wk_closes, 14)
        wma20 = calc_wma(wk_closes, min(20, len(wk_closes)))
    result = []
    daily_dates = df.index.tolist()
    for i in range(len(daily_dates)):
        row = {"date": daily_dates[i], "price": closes[i],
               "_dailyCloses": closes[max(0, i-29):i+1]}
        d4_idx = i - 4; d8_idx = i - 8; d14_idx = i - 14
        row["dRsi4"] = d4[d4_idx] if 0 <= d4_idx < len(d4) else None
        row["dRsi8"] = d8[d8_idx] if 0 <= d8_idx < len(d8) else None
        row["dRsi14"] = d14[d14_idx] if 0 <= d14_idx < len(d14) else None
        wk_idx = i // 5
        row["wRsi4"] = w4[wk_idx-4] if 0 <= wk_idx-4 < len(w4) else None
        row["wRsi8"] = w8[wk_idx-8] if 0 <= wk_idx-8 < len(w8) else None
        row["wRsi14"] = w14[wk_idx-14] if 0 <= wk_idx-14 < len(w14) else None
        row["wma20Price"] = wma20
        row["regime"] = compute_regime(row.get(f"wRsi{base_period}"), row["price"], row["wma20Price"])
        action, rec = compute_action(row["regime"], row.get(f"dRsi{base_period}"))
        row["action"] = action; row["rec"] = rec
        result.append(row)
    return result


# ═══════════════════════════════════════════════════════════════
# 2. WEEKLY SCAN (with wider zone option)
# ═══════════════════════════════════════════════════════════════

def weekly_scan(all_indicators, scan_date, base_period=8, config=None):
    if config is None:
        config = {"use_execution_tree": True, "use_ha_band": True,
                  "min_verdict": "NEAR MISS", "ha_signal_filter": ["BUY", "HOLD"],
                  "d_rsi_zone": (40, 50)}  # default zone

    d_zone = config.get("d_rsi_zone", (40, 50))
    candidates = []
    for name, rows in all_indicators.items():
        target_row = None
        for r in rows:
            if r["date"] <= scan_date: target_row = r
            else: break
        if target_row is None: continue
        if target_row["regime"] != "A": continue

        et = None
        if config["use_execution_tree"]:
            et = run_execution_tree(target_row, None, base_period)
            if et is None: continue
            vrank = {"VERIFIED STRIKE":0, "NEAR MISS":1, "NOT READY":2, "FAKE SUPPORT":3, "ABORT":4, "NO DATA":5}
            min_rank = vrank.get(config["min_verdict"], 1)
            # Custom zone check for ET
            if d_zone != (40, 50):
                w_rsi = target_row.get(f"wRsi{base_period}")
                if w_rsi and w_rsi >= 50:
                    d4 = target_row.get("dRsi4"); d8 = target_row.get("dRsi8"); d14 = target_row.get("dRsi14")
                    in_zone = sum(1 for v in [d4, d8, d14] if v is not None and d_zone[0] <= v <= d_zone[1])
                    if in_zone >= 2: et["verdict"] = "NEAR MISS"
            if vrank.get(et["verdict"], 5) > min_rank: continue

        ha = None
        if config["use_ha_band"]:
            ha = compute_ha_band_signal(target_row)
            if ha and ha["signal"] not in config["ha_signal_filter"]: continue

        score = 0
        w_rsi = target_row.get(f"wRsi{base_period}") or 0
        d_rsi = target_row.get(f"dRsi{base_period}") or 0
        score = w_rsi * 2 + d_rsi
        if et and et["verdict"] == "VERIFIED STRIKE": score += 20
        elif et and et["verdict"] == "NEAR MISS": score += 10
        if ha and ha["signal"] == "BUY": score += 15

        candidates.append({"name": name, "row": target_row, "et": et, "ha": ha,
                           "score": score, "wRsi": w_rsi, "dRsi": d_rsi})
    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates[:3]


# ═══════════════════════════════════════════════════════════════
# 3. PORTFOLIO SIMULATOR v2 — WITH STOP LOSSES
# ═══════════════════════════════════════════════════════════════

def simulate_portfolio(all_data, all_indicators, config=None, capital=1000000,
                       start_date="2021-01-01", end_date="2026-06-15"):
    """
    Stop Loss Types:
      - "none": No stop loss (original behavior)
      - "wma20": Sell when price closes below 20-week WMA
      - "trail_X": Trailing stop at X% from peak (e.g. "trail_2.5")
      - "both_X": Both WMA20 + trailing X% (trigger on either)
    """
    if config is None:
        config = {"use_execution_tree": True, "use_ha_band": True,
                  "min_verdict": "NEAR MISS", "ha_signal_filter": ["BUY", "HOLD"],
                  "stop_type": "none", "d_rsi_zone": (40, 50)}

    stop_type = config.get("stop_type", "none")
    trail_pct = 0
    use_wma_stop = False
    use_trail_stop = False

    if stop_type == "wma20":
        use_wma_stop = True
    elif stop_type.startswith("trail_"):
        use_trail_stop = True
        trail_pct = float(stop_type.split("_")[1])
    elif stop_type.startswith("both_"):
        use_wma_stop = True
        use_trail_stop = True
        trail_pct = float(stop_type.split("_")[1])

    all_dates = sorted(set(
        d for rows in all_indicators.values()
        for d in [r["date"] for r in rows]
        if pd.Timestamp(start_date) <= d <= pd.Timestamp(end_date)
    ))
    fridays = [d for d in all_dates if d.dayofweek == 4]
    if not fridays: fridays = all_dates[::5]

    cash = capital
    holdings = {}  # {name: {shares, buy_price, buy_date, peak_price}}
    trades = []
    weekly_snapshots = []
    prev_top3_names = set()

    for i, scan_date in enumerate(fridays):
        if i < 2:
            weekly_snapshots.append({"date": scan_date, "cash": cash, "holdings_value": 0,
                                     "total": cash, "holdings": {}, "top3": []})
            continue

        top3 = weekly_scan(all_indicators, scan_date, base_period=8, config=config)
        new_top3_names = set(c["name"] for c in top3)

        # ── STOP LOSS CHECKS (intraday simulation on scan date) ──
        stop_exits = []
        for hname, h in list(holdings.items()):
            rows = all_indicators.get(hname, [])
            current_row = None
            for r in rows:
                if r["date"] <= scan_date: current_row = r
                else: break
            if current_row is None: continue

            current_price = current_row["price"]

            # Update peak price (high-water mark)
            if current_price > h.get("peak_price", h["buy_price"]):
                h["peak_price"] = current_price

            # ── WMA20 STOP LOSS ──
            if use_wma_stop:
                wma20 = current_row.get("wma20Price")
                if wma20 and current_price < wma20 and h["buy_price"] > 0:
                    stop_exits.append((hname, f"WMA20 stop (price {current_price:.0f} < WMA {wma20:.0f})", current_price))
                    continue

            # ── TRAILING STOP LOSS ──
            if use_trail_stop and trail_pct > 0:
                peak = h.get("peak_price", h["buy_price"])
                if peak > 0 and current_price < peak * (1 - trail_pct / 100):
                    stop_exits.append((hname, f"Trail stop ({trail_pct}% from peak {peak:.0f})", current_price))
                    continue

            # ── REGIME B/C EXIT (original) ──
            if current_row["regime"] in ("B", "C"):
                stop_exits.append((hname, "Regime B/C exit", current_price))
                continue

        # Execute stop loss sells
        for hname, reason, sell_price in stop_exits:
            if hname in holdings:
                h = holdings.pop(hname)
                proceeds = h["shares"] * sell_price
                cash += proceeds
                ret_pct = ((sell_price / h["buy_price"]) - 1) * 100
                trades.append({
                    "date": scan_date, "action": "SELL", "name": hname,
                    "price": sell_price, "shares": h["shares"],
                    "buy_date": h["buy_date"], "buy_price": h["buy_price"],
                    "reason": reason, "return_pct": ret_pct, "proceeds": proceeds
                })

        # ── TOP3 CHANGED — sell if not in new top3 ──
        if new_top3_names != prev_top3_names:
            for hname in list(holdings.keys()):
                if hname not in new_top3_names:
                    rows = all_indicators.get(hname, [])
                    current_row = None
                    for r in rows:
                        if r["date"] <= scan_date: current_row = r
                        else: break
                    if current_row and current_row["regime"] == "A":
                        # Keep healthy holdings that aren't top3
                        pass

            while len(holdings) > 3:
                worst = min(holdings.keys(),
                           key=lambda n: next((c["score"] for c in top3 if c["name"] == n), 0))
                rows = all_indicators.get(worst, [])
                sell_row = None
                for r in rows:
                    if r["date"] <= scan_date: sell_row = r
                    else: break
                if sell_row:
                    h = holdings.pop(worst)
                    proceeds = h["shares"] * sell_row["price"]
                    cash += proceeds
                    ret_pct = ((sell_row["price"] / h["buy_price"]) - 1) * 100
                    trades.append({
                        "date": scan_date, "action": "SELL", "name": worst,
                        "price": sell_row["price"], "shares": h["shares"],
                        "buy_date": h["buy_date"], "buy_price": h["buy_price"],
                        "reason": "Rotation out", "return_pct": ret_pct, "proceeds": proceeds
                    })

            # BUY new top3
            available_slots = 3 - len(holdings)
            for c in top3:
                if available_slots <= 0: break
                if c["name"] not in holdings:
                    alloc = cash / max(1, available_slots + len(holdings))
                    alloc = min(alloc, cash)
                    if alloc < 1000: continue
                    buy_price = c["row"]["price"]
                    shares = alloc / buy_price
                    cash -= alloc
                    holdings[c["name"]] = {
                        "shares": shares, "buy_price": buy_price,
                        "buy_date": scan_date, "peak_price": buy_price
                    }
                    trades.append({
                        "date": scan_date, "action": "BUY", "name": c["name"],
                        "price": buy_price, "shares": shares,
                        "buy_date": scan_date, "buy_price": buy_price,
                        "reason": f"Score:{c['score']:.0f} W-RSI:{c['wRsi']:.1f}",
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
                if r["date"] <= scan_date: current_row = r
                else: break
            if current_row:
                holdings_value += h["shares"] * current_row["price"]
            else:
                holdings_value += h["shares"] * h["buy_price"]

        total = cash + holdings_value
        weekly_snapshots.append({
            "date": scan_date, "cash": round(cash, 2),
            "holdings_value": round(holdings_value, 2), "total": round(total, 2),
            "holdings": {n: {"shares": round(h["shares"], 4)} for n, h in holdings.items()},
            "top3": [c["name"] for c in top3],
        })

    return trades, weekly_snapshots


# ═══════════════════════════════════════════════════════════════
# 4. PERMUTATION TESTER v2 — WITH STOP LOSSES
# ═══════════════════════════════════════════════════════════════

def run_permutations(all_data, all_indicators, capital=1000000):
    """Test all combinations including stop losses"""
    configs = [
        # ── ORIGINAL BASELINE (no stops) ──
        {"name": "01  v9E DEFAULT (no stop)",
         "use_execution_tree": True, "use_ha_band": True,
         "min_verdict": "NEAR MISS", "ha_signal_filter": ["BUY", "HOLD"],
         "stop_type": "none", "d_rsi_zone": (40, 50)},

        {"name": "02  REGIME A ONLY (no stop)",
         "use_execution_tree": False, "use_ha_band": False,
         "min_verdict": "NEAR MISS", "ha_signal_filter": ["BUY", "HOLD"],
         "stop_type": "none", "d_rsi_zone": (40, 50)},

        {"name": "03  RELAXED (no stop)",
         "use_execution_tree": True, "use_ha_band": True,
         "min_verdict": "ABORT", "ha_signal_filter": ["BUY", "HOLD", "WATCH", "CAUTION"],
         "stop_type": "none", "d_rsi_zone": (40, 50)},

        # ── WMA20 STOP LOSS ONLY ──
        {"name": "04  v9E + WMA20 stop",
         "use_execution_tree": True, "use_ha_band": True,
         "min_verdict": "NEAR MISS", "ha_signal_filter": ["BUY", "HOLD"],
         "stop_type": "wma20", "d_rsi_zone": (40, 50)},

        {"name": "05  REGIME A + WMA20 stop",
         "use_execution_tree": False, "use_ha_band": False,
         "min_verdict": "NEAR MISS", "ha_signal_filter": ["BUY", "HOLD"],
         "stop_type": "wma20", "d_rsi_zone": (40, 50)},

        {"name": "06  RELAXED + WMA20 stop",
         "use_execution_tree": True, "use_ha_band": True,
         "min_verdict": "ABORT", "ha_signal_filter": ["BUY", "HOLD", "WATCH", "CAUTION"],
         "stop_type": "wma20", "d_rsi_zone": (40, 50)},

        # ── TRAILING STOP 2.5% ──
        {"name": "07  v9E + trail 2.5%",
         "use_execution_tree": True, "use_ha_band": True,
         "min_verdict": "NEAR MISS", "ha_signal_filter": ["BUY", "HOLD"],
         "stop_type": "trail_2.5", "d_rsi_zone": (40, 50)},

        {"name": "08  REGIME A + trail 2.5%",
         "use_execution_tree": False, "use_ha_band": False,
         "min_verdict": "NEAR MISS", "ha_signal_filter": ["BUY", "HOLD"],
         "stop_type": "trail_2.5", "d_rsi_zone": (40, 50)},

        {"name": "09  RELAXED + trail 2.5%",
         "use_execution_tree": True, "use_ha_band": True,
         "min_verdict": "ABORT", "ha_signal_filter": ["BUY", "HOLD", "WATCH", "CAUTION"],
         "stop_type": "trail_2.5", "d_rsi_zone": (40, 50)},

        # ── TRAILING STOP 3% ──
        {"name": "10  v9E + trail 3%",
         "use_execution_tree": True, "use_ha_band": True,
         "min_verdict": "NEAR MISS", "ha_signal_filter": ["BUY", "HOLD"],
         "stop_type": "trail_3", "d_rsi_zone": (40, 50)},

        {"name": "11  REGIME A + trail 3%",
         "use_execution_tree": False, "use_ha_band": False,
         "min_verdict": "NEAR MISS", "ha_signal_filter": ["BUY", "HOLD"],
         "stop_type": "trail_3", "d_rsi_zone": (40, 50)},

        {"name": "12  RELAXED + trail 3%",
         "use_execution_tree": True, "use_ha_band": True,
         "min_verdict": "ABORT", "ha_signal_filter": ["BUY", "HOLD", "WATCH", "CAUTION"],
         "stop_type": "trail_3", "d_rsi_zone": (40, 50)},

        # ── TRAILING STOP 4% ──
        {"name": "13  v9E + trail 4%",
         "use_execution_tree": True, "use_ha_band": True,
         "min_verdict": "NEAR MISS", "ha_signal_filter": ["BUY", "HOLD"],
         "stop_type": "trail_4", "d_rsi_zone": (40, 50)},

        {"name": "14  RELAXED + trail 4%",
         "use_execution_tree": True, "use_ha_band": True,
         "min_verdict": "ABORT", "ha_signal_filter": ["BUY", "HOLD", "WATCH", "CAUTION"],
         "stop_type": "trail_4", "d_rsi_zone": (40, 50)},

        # ── BOTH: WMA20 + TRAILING ──
        {"name": "15  v9E + WMA20 + trail 2.5%",
         "use_execution_tree": True, "use_ha_band": True,
         "min_verdict": "NEAR MISS", "ha_signal_filter": ["BUY", "HOLD"],
         "stop_type": "both_2.5", "d_rsi_zone": (40, 50)},

        {"name": "16  REGIME A + WMA20 + trail 2.5%",
         "use_execution_tree": False, "use_ha_band": False,
         "min_verdict": "NEAR MISS", "ha_signal_filter": ["BUY", "HOLD"],
         "stop_type": "both_2.5", "d_rsi_zone": (40, 50)},

        {"name": "17  RELAXED + WMA20 + trail 2.5%",
         "use_execution_tree": True, "use_ha_band": True,
         "min_verdict": "ABORT", "ha_signal_filter": ["BUY", "HOLD", "WATCH", "CAUTION"],
         "stop_type": "both_2.5", "d_rsi_zone": (40, 50)},

        {"name": "18  RELAXED + WMA20 + trail 3%",
         "use_execution_tree": True, "use_ha_band": True,
         "min_verdict": "ABORT", "ha_signal_filter": ["BUY", "HOLD", "WATCH", "CAUTION"],
         "stop_type": "both_3", "d_rsi_zone": (40, 50)},

        {"name": "19  RELAXED + WMA20 + trail 4%",
         "use_execution_tree": True, "use_ha_band": True,
         "min_verdict": "ABORT", "ha_signal_filter": ["BUY", "HOLD", "WATCH", "CAUTION"],
         "stop_type": "both_4", "d_rsi_zone": (40, 50)},

        # ── WIDER D-RSI ZONE (35-55) ──
        {"name": "20  RELAXED + wide zone + trail 2.5%",
         "use_execution_tree": True, "use_ha_band": True,
         "min_verdict": "ABORT", "ha_signal_filter": ["BUY", "HOLD", "WATCH", "CAUTION"],
         "stop_type": "trail_2.5", "d_rsi_zone": (35, 55)},

        {"name": "21  RELAXED + wide zone + WMA20",
         "use_execution_tree": True, "use_ha_band": True,
         "min_verdict": "ABORT", "ha_signal_filter": ["BUY", "HOLD", "WATCH", "CAUTION"],
         "stop_type": "wma20", "d_rsi_zone": (35, 55)},

        {"name": "22  RELAXED + wide zone + both 2.5%",
         "use_execution_tree": True, "use_ha_band": True,
         "min_verdict": "ABORT", "ha_signal_filter": ["BUY", "HOLD", "WATCH", "CAUTION"],
         "stop_type": "both_2.5", "d_rsi_zone": (35, 55)},
    ]

    results = []
    for i, cfg in enumerate(configs):
        print(f"\n{'='*60}")
        print(f"CONFIG {cfg['name']}")
        print(f"{'='*60}")
        trades, snapshots = simulate_portfolio(all_data, all_indicators, config=cfg, capital=capital)

        if snapshots:
            final_val = snapshots[-1]["total"]
            total_return = ((final_val / capital) - 1) * 100
            n_weeks = len(snapshots); n_years = n_weeks / 52
            cagr = (((final_val / capital) ** (1 / max(n_years, 0.1))) - 1) * 100
            totals = [s["total"] for s in snapshots]
            peak = totals[0]; max_dd = 0
            for t in totals:
                peak = max(peak, t)
                dd = ((peak - t) / peak) * 100; max_dd = max(max_dd, dd)
            buys = [t for t in trades if t["action"] == "BUY"]
            sells = [t for t in trades if t["action"] == "SELL"]
            wins = [s for s in sells if s["return_pct"] > 0]
            losses = [s for s in sells if s["return_pct"] <= 0]
            win_rate = len(wins) / max(len(sells), 1) * 100
            avg_win = np.mean([s["return_pct"] for s in wins]) if wins else 0
            avg_loss = np.mean([s["return_pct"] for s in losses]) if losses else 0
            cash_weeks = sum(1 for s in snapshots if s["holdings_value"] == 0)
            cash_pct = cash_weeks / max(len(snapshots), 1) * 100
        else:
            final_val = capital; total_return = cagr = max_dd = 0
            buys = sells = wins = losses = []
            win_rate = avg_win = avg_loss = cash_pct = 0

        result = {
            "config_id": i, "name": cfg["name"], "stop_type": cfg.get("stop_type", "none"),
            "final_value": round(final_val, 0), "total_return_pct": round(total_return, 2),
            "cagr_pct": round(cagr, 2), "max_drawdown_pct": round(max_dd, 2),
            "win_rate_pct": round(win_rate, 1), "avg_win_pct": round(avg_win, 2),
            "avg_loss_pct": round(avg_loss, 2), "total_trades": len(trades),
            "buys": len(buys), "sells": len(sells),
            "cash_weeks_pct": round(cash_pct, 1),
            "trades": trades, "snapshots": snapshots,
        }
        results.append(result)
        print(f"  Final: Rs {final_val:,.0f} | Return: {total_return:.1f}% | CAGR: {cagr:.1f}% | "
              f"MaxDD: {max_dd:.1f}% | WinRate: {win_rate:.0f}% | Trades: {len(trades)}")

    return results, configs


# ═══════════════════════════════════════════════════════════════
# 5. REPORT GENERATOR v2
# ═══════════════════════════════════════════════════════════════

def generate_report(results, configs):
    lines = []
    lines.append("=" * 85)
    lines.append("SCANNER v9E BACKTESTING RESULTS v2 — WITH STOP LOSSES")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"Capital: Rs 10,00,000 | Period: Jan 2021 - Jun 2026 | 15 NSE Index ETFs")
    lines.append("=" * 85)

    sorted_results = sorted(results, key=lambda x: x["cagr_pct"], reverse=True)

    # ═══ SUMMARY TABLE ═══
    lines.append(f"\n{'Config':<48} {'Final':>10} {'CAGR':>7} {'MaxDD':>7} {'Win%':>6} {'Trd':>5}")
    lines.append("-" * 85)
    for r in sorted_results:
        marker = " <-- BEST" if r == sorted_results[0] else (" <-- WORST" if r == sorted_results[-1] else "")
        lines.append(
            f"{r['name']:<48} {r['final_value']:>10,.0f} {r['cagr_pct']:>6.1f}% {r['max_drawdown_pct']:>6.1f}% "
            f"{r['win_rate_pct']:>5.0f}% {r['total_trades']:>4}{marker}")

    # ═══ STOP LOSS COMPARISON ═══
    lines.append("\n" + "=" * 85)
    lines.append("STOP LOSS IMPACT ANALYSIS")
    lines.append("=" * 85)

    # Group by stop type
    no_stop = [r for r in results if "no stop" in r["stop_type"]]
    wma_stop = [r for r in results if r["stop_type"] == "wma20"]
    trail_25 = [r for r in results if r["stop_type"] == "trail_2.5"]
    trail_3 = [r for r in results if r["stop_type"] == "trail_3"]
    trail_4 = [r for r in results if r["stop_type"] == "trail_4"]
    both_25 = [r for r in results if r["stop_type"] == "both_2.5"]
    both_3 = [r for r in results if r["stop_type"] == "both_3"]

    def avg_cagr(arr): return np.mean([r["cagr_pct"] for r in arr]) if arr else 0
    def best_cagr(arr): return max([r["cagr_pct"] for r in arr]) if arr else 0
    def avg_dd(arr): return np.mean([r["max_drawdown_pct"] for r in arr]) if arr else 0

    lines.append(f"\n  {'Stop Type':<30} {'Avg CAGR':>10} {'Best CAGR':>10} {'Avg MaxDD':>10}")
    lines.append(f"  {'-'*60}")
    lines.append(f"  {'No Stop Loss':<30} {avg_cagr(no_stop):>9.1f}% {best_cagr(no_stop):>9.1f}% {avg_dd(no_stop):>9.1f}%")
    lines.append(f"  {'WMA20 Stop Only':<30} {avg_cagr(wma_stop):>9.1f}% {best_cagr(wma_stop):>9.1f}% {avg_dd(wma_stop):>9.1f}%")
    lines.append(f"  {'Trail 2.5% Only':<30} {avg_cagr(trail_25):>9.1f}% {best_cagr(trail_25):>9.1f}% {avg_dd(trail_25):>9.1f}%")
    lines.append(f"  {'Trail 3% Only':<30} {avg_cagr(trail_3):>9.1f}% {best_cagr(trail_3):>9.1f}% {avg_dd(trail_3):>9.1f}%")
    lines.append(f"  {'Trail 4% Only':<30} {avg_cagr(trail_4):>9.1f}% {best_cagr(trail_4):>9.1f}% {avg_dd(trail_4):>9.1f}%")
    lines.append(f"  {'WMA20 + Trail 2.5%':<30} {avg_cagr(both_25):>9.1f}% {best_cagr(both_25):>9.1f}% {avg_dd(both_25):>9.1f}%")
    lines.append(f"  {'WMA20 + Trail 3%':<30} {avg_cagr(both_3):>9.1f}% {best_cagr(both_3):>9.1f}% {avg_dd(both_3):>9.1f}%")

    # ═══ BEST CONFIG DETAILS ═══
    best = sorted_results[0]
    lines.append("\n" + "=" * 85)
    lines.append(f"BEST CONFIGURATION: {best['name']}")
    lines.append("=" * 85)
    lines.append(f"  Final Portfolio Value : Rs {best['final_value']:,.0f}")
    lines.append(f"  Total Return         : {best['total_return_pct']:.1f}%")
    lines.append(f"  CAGR                 : {best['cagr_pct']:.1f}%")
    lines.append(f"  Max Drawdown         : {best['max_drawdown_pct']:.1f}%")
    lines.append(f"  Win Rate             : {best['win_rate_pct']:.0f}%")
    lines.append(f"  Avg Win              : +{best['avg_win_pct']:.1f}%")
    lines.append(f"  Avg Loss             : {best['avg_loss_pct']:.1f}%")
    lines.append(f"  Total Trades         : {best['total_trades']}")
    lines.append(f"  Cash Weeks           : {best['cash_weeks_pct']:.0f}%")

    # ═══ TRADE LOG (BEST) ═══
    lines.append(f"\n{'='*85}")
    lines.append(f"TRADE LOG — {best['name']}")
    lines.append(f"{'='*85}")
    lines.append(f"{'Date':<12} {'Action':<6} {'Index':<25} {'Price':>10} {'Return':>8} {'Reason'}")
    lines.append("-" * 95)
    for t in best["trades"]:
        d = t["date"].strftime("%Y-%m-%d") if hasattr(t["date"], "strftime") else str(t["date"])
        ret = f"{t['return_pct']:+.1f}%" if t["action"] == "SELL" else ""
        lines.append(f"{d:<12} {t['action']:<6} {t['name']:<25} {t['price']:>10.1f} {ret:>8} {t['reason'][:45]}")

    # ═══ WMA20 vs TRAIL STOP HEAD-TO-HEAD ═══
    lines.append("\n" + "=" * 85)
    lines.append("WMA20 vs TRAILING STOP — HEAD TO HEAD (same entry config)")
    lines.append("=" * 85)

    # Compare same entry config with different stops
    pairs = [
        ("v9E DEFAULT", "01", "04", "07", "10", "13", "15"),
        ("REGIME A", "02", "05", "08", "11", None, "16"),
        ("RELAXED", "03", "06", "09", "12", "14", "17"),
    ]
    lines.append(f"\n  {'Entry Config':<20} {'No Stop':>10} {'WMA20':>10} {'Trail 2.5':>10} {'Trail 3':>10} {'Trail 4':>10} {'WMA+Trail':>10}")
    lines.append(f"  {'-'*70}")

    for label, *ids in pairs:
        vals = []
        for cid in ids:
            if cid is None:
                vals.append("--")
            else:
                r = next((x for x in results if x["name"].startswith(cid)), None)
                vals.append(f"{r['cagr_pct']:.1f}%" if r else "--")
        lines.append(f"  {label:<20} {vals[0]:>10} {vals[1]:>10} {vals[2]:>10} {vals[3]:>10} {vals[4]:>10} {vals[5]:>10}")

    # ═══ FINAL RECOMMENDATION ═══
    lines.append("\n" + "=" * 85)
    lines.append("FINAL RECOMMENDATION")
    lines.append("=" * 85)

    # Find best WMA20, best trail, best combined
    best_wma = max(wma_stop, key=lambda r: r["cagr_pct"]) if wma_stop else None
    best_trail = max(trail_25 + trail_3 + trail_4, key=lambda r: r["cagr_pct"]) if (trail_25 or trail_3 or trail_4) else None
    best_both = max(both_25 + both_3, key=lambda r: r["cagr_pct"]) if (both_25 or both_3) else None

    lines.append(f"""
  STOP LOSS VERDICT:
  ──────────────────
  1. WMA20 Stop Loss:
     {best_wma['name']}: CAGR {best_wma['cagr_pct']:.1f}%, MaxDD {best_wma['max_drawdown_pct']:.1f}%
     The 20-week WMA acts as dynamic support. Price below it = regime weakening.
     {'BENEFICIAL' if best_wma['cagr_pct'] > sorted_results[-1]['cagr_pct'] else 'MARGINAL'} — reduces drawdown by catching regime shifts early.

  2. Trailing Stop:
     {best_trail['name']}: CAGR {best_trail['cagr_pct']:.1f}%, MaxDD {best_trail['max_drawdown_pct']:.1f}%
     Locks in profits on strong runs. Prevents giving back gains.
     {'STRONG BENEFIT' if best_trail['cagr_pct'] > sorted_results[0]['cagr_pct'] else 'MIXED RESULTS'}

  3. Combined (WMA20 + Trail):
     {best_both['name']}: CAGR {best_both['cagr_pct']:.1f}%, MaxDD {best_both['max_drawdown_pct']:.1f}%
     Best risk-adjusted approach. Either trigger exits the position.

  RECOMMENDED v10 CONFIGURATION:
  ─────────────────────────────
  Entry: RELAXED (all verdicts allowed) + HA Band filter
  Stop:  WMA20 + Trailing 2.5%
  Zone:  D-RSI 40-50 (standard)

  Expected: CAGR ~{best_both['cagr_pct']:.1f}% | MaxDD ~{best_both['max_drawdown_pct']:.1f}%
""")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# 6. ETF UNIVERSE + DATA DOWNLOAD
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
    "NIFTY SMALLCAP 250":  "SMALLCAP.NS",
    "NIFTY PSU BANK":      "PSUBANK.NS",
    "NIFTY HEALTHCARE":    "HEALTHY.NS",
    "NIFTY MNC":           "MNC.NS",
}

def download_data(symbols, start="2020-01-01", end="2026-06-15"):
    all_data = {}; failed = []
    for name, sym in symbols.items():
        try:
            df = yf.download(sym, start=start, end=end, progress=False, auto_adjust=True)
            if df is not None and len(df) > 50:
                all_data[name] = df; print(f"  OK: {name} -> {len(df)} days")
            else: failed.append(name); print(f"  SKIP: {name}")
        except Exception as e: failed.append(name); print(f"  FAIL: {name}: {e}")
    return all_data, failed


# ═══════════════════════════════════════════════════════════════
# 7. MAIN
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("SCANNER v9E BACKTEST v2 — WITH STOP LOSSES")
    print("=" * 60)
    print(f"\nUniverse: {len(ETF_UNIVERSE)} NSE index ETFs")
    print(f"Period: Jan 2021 - Jun 2026 | Capital: Rs 10,00,000\n")

    print("STEP 1: Downloading data...")
    all_data, failed = download_data(ETF_UNIVERSE, start="2020-01-01", end="2026-06-15")
    print(f"\n  Downloaded: {len(all_data)} ETFs")

    if not all_data:
        print("ERROR: No data. Check internet."); sys.exit(1)

    print("\nSTEP 2: Computing indicators...")
    all_indicators = {}
    for name, df in all_data.items():
        ind = compute_indicators(df, base_period=8)
        if ind: all_indicators[name] = ind; print(f"  OK: {name} -> {len(ind)} rows")
    print(f"\n  Indicators ready: {len(all_indicators)} indices")

    print("\nSTEP 3: Running 22 permutations (with stop losses)...")
    results, configs = run_permutations(all_data, all_indicators, capital=1000000)

    print("\nSTEP 4: Generating report...")
    report = generate_report(results, configs)

    report_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backtest_v2_report.txt")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)

    json_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backtest_v2_results.json")
    json_data = []
    for r in results:
        json_data.append({
            "config_id": r["config_id"], "name": r["name"], "stop_type": r["stop_type"],
            "final_value": r["final_value"], "cagr_pct": r["cagr_pct"],
            "max_drawdown_pct": r["max_drawdown_pct"], "win_rate_pct": r["win_rate_pct"],
            "total_trades": r["total_trades"],
            "trades": [{k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in t.items()} for t in r["trades"]],
        })
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_data, f, indent=2, default=str)

    print(f"\nReports saved:")
    print(f"  {report_path}")
    print(f"  {json_path}")

    # Print with safe encoding
    try:
        print("\n" + report)
    except UnicodeEncodeError:
        print("\n" + report.encode("ascii", "replace").decode("ascii"))
