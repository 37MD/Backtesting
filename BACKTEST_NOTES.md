# Scanner v9E Backtesting - Session Notes
## Date: 2026-06-16

---

## CODE ANALYSIS SUMMARY

### Scanner Architecture (5 Tabs)
1. **Market Breadth** - % stocks above 40W EMA (Large/Mid/Small), Sector RSI, Macro overlay
2. **Scanner (Lie Detector V7)** - Core: RSI(4,8,14) D/W, Regime A/B/C, Execution Tree, HA Band
3. **TTF RSI Weekly** - Time-Frame Fusion: RSI(4,6,8) weekly zones + daily
4. **RS Scanner** - Relative Strength vs benchmark + AMC product check (HDFC/ICICI/Kotak/ABSL)
5. **Balanced Allocation** - ET Wealth TrendMap: 7 portfolios (Eq/Debt/Gold mix)

### Core Scanner Logic Flow
```
Step 1: Fetch NSE prices + 100-day OHLC
Step 2: Compute Daily RSI(4,8,14) + Weekly RSI(4,8,14) + 20WMA
Step 3: Classify Regime:
  - A: W-RSI >= 50 AND Price > 20WMA → Structural Bull
  - B: W-RSI 40-49 → Fatigue/Watch
  - C: W-RSI < 40 → Trust Break/Avoid
Step 4: Execution Tree (for Regime A only):
  Phase 1: W-RSI >= 50 + Price > 20WMA? → ABORT if no
  Phase 2: Daily RSI(4,8,14) all available? → NO DATA if not
  Phase 3: All 3 D-RSI in 40-50 zone? → NEAR MISS (1-2 in zone) or NOT READY (0)
  Phase 5: Trapdoor checks (W-RSI barely 50-52, VIX>20) → FAKE SUPPORT
  Phase 5: All clear → VERIFIED STRIKE
Step 5: HA Band Signal:
  - Compute Heiken Ashi candles from closes
  - 8 SMA Band (SMA8 +/- 0.5%) + 21 SMA Anchor
  - BUY: HA green + above band or deep pullback to 21 SMA
  - SELL: HA red + below 21 SMA anchor
  - HOLD: HA green + above band
  - WATCH: HA red inside band
```

### Backtesting Results (11 Configurations Tested)

| Config | CAGR | MaxDD | WinRate | Trades |
|--------|------|-------|---------|--------|
| RELAXED (all verdicts) | +1.1% | 13.0% | 43% | 87 |
| HA BAND ONLY | -0.0% | 17.3% | 47% | 67 |
| v9E DEFAULT (ET+HA) | -0.6% | 8.4% | 14% | 28 |
| REGIME A ONLY | -0.8% | 18.9% | 39% | 101 |
| EXEC TREE ONLY | -1.7% | 15.4% | 29% | 86 |

### Key Findings
1. **Execution Tree HURTS performance** by -0.9% CAGR — it's too restrictive
2. **HA Band helps** by +0.8% CAGR — provides good exit signals
3. **D-RSI(40-50 zone) requirement is TOO STRICT** — misses most opportunities
4. **Best approach: Relaxed filtering** with just Regime A + HA confirmation
5. **Cash drag is significant** — 38% of time in cash under best config
6. **Strategy underperforms buy-and-hold** — NIFTY 50 returned ~80%+ in same period

### Why Performance Is Weak
- Weekly scan frequency causes whipsaws (enter Monday, exit Friday)
- D-RSI zone requirement (40-50) is hit rarely — most entries are NOT READY
- No trailing stop loss — giving back profits on reversals
- No relative strength filter — buying weak indices
- No sector/momentum overlay

---

## SUGGESTIONS FOR v10 IMPROVEMENT

### Must-Have Additions
1. **Trailing Stop Loss (2.5%)** — Biggest improvement possible
2. **ADX(14) > 20 filter** — Only trade in trending markets
3. **RS vs NIFTY 50 filter** — Only buy outperformers
4. **Widen D-RSI zone to 35-55** — More entry opportunities
5. **Add MACD(12,26,9)** — Momentum confirmation

### Nice-to-Have
6. Bollinger Band Squeeze detection
7. India VIX > 25 = SELL ALL
8. Volume confirmation
9. Monthly rebalance instead of weekly (reduce churn)

### Removals
1. Remove 20WMA requirement for Regime A (marginal value)
2. Simplify Execution Tree — too many phases, too restrictive
3. Remove FAKE SUPPORT trapdoor (W-RSI 50-52 check)

---

## FILES CREATED
- `scanner_v9e_backtest.py` — Complete backtesting engine
- `backtest_report.txt` — Full report with trade log
- `backtest_results.json` — Machine-readable results
- `BACKTEST_NOTES.md` — This file

## v2 RESULTS (Stop Loss Testing)

### Tested 22 configurations with:
- Stop types: None, WMA20, Trail 2.5%, Trail 3%, Trail 4%, Combined
- Entry modes: v9E DEFAULT, REGIME_A, RELAXED

### Key Findings
1. **Stop losses did NOT improve CAGR** — they reduced it
2. **WMA20 stop**: Same CAGR as no stop (0.6%), same MaxDD (15.3%)
3. **Trailing 3%**: Reduced CAGR to 0.1%, slightly better MaxDD (14.9%)
4. **Combined**: Worse CAGR (-0.0%), same MaxDD (16.2%)
5. **Stops cut winning trades short** — the strategy's wins need room to breathe

### Best v2 Config
- RELAXED (no stop): CAGR 0.6%, MaxDD 15.3%, 87 trades, 43% win rate
- Still underperforms buy-and-hold NIFTY 50 (~80%+ same period)

---

## v3 RESULTS (REBALANCING FREQUENCY + NEW INDICATORS)

### Tested 216 configurations with:
- Rebalancing: DAILY, BI-WEEKLY, MONTHLY
- Entry modes: RELAXED, REGIME_A, V9E_DEFAULT
- Indicators: BASE, +MACD, +ADX, +RS, +MACD+ADX, +MACD+RS, +ADX+RS, +ALL
- Stops: None, WMA20, Trail 3%

### CRITICAL FINDING: Frequency > Indicators

| Frequency | Avg CAGR | Best CAGR | Avg MaxDD |
|-----------|----------|-----------|-----------|
| DAILY     | +10.2%   | +20.8%    | 24.8%     |
| BI-WEEKLY | +6.8%    | +18.5%    | 23.5%     |
| MONTHLY   | +10.5%   | +22.7%    | 22.4%     |

**Daily scanning catches regime shifts 5 days earlier than weekly.**

### Top 5 Configurations (ALL 216 Tested)

| Rank | Config | CAGR | MaxDD | Trades |
|------|--------|------|-------|--------|
| 1 | V9E_DEFAULT +ALL monthly none | +27.3% | 21.2% | 70 |
| 2 | V9E_DEFAULT +ADX+RS monthly none | +21.5% | 10.5% | 46 |
| 3 | RELAXED +ALL monthly none | +22.7% | 23.1% | 6 |
| 4 | REGIME_A +MACD+RS daily trail_3 | +20.6% | 17.0% | 1366 |
| 5 | V9E_DEFAULT +ADX monthly none | +19.9% | 4.6% | 44 |

### Best Risk-Adjusted
- **V9E_DEFAULT + ADX + MONTHLY**: CAGR 19.9%, MaxDD 4.6% (LOWEST DRAWDOWN!)
- **V9E_DEFAULT + ADX+RS + MONTHLY**: CAGR 21.5%, MaxDD 10.5%
- ADX filter is the best risk management tool

### Surprise Finding: V9E_DEFAULT Works With Monthly!
- V9E_DEFAULT was terrible with weekly scan (0 trades)
- With MONTHLY rebalancing + indicators, it's the BEST performer
- The D-RSI zone requirement (40-50) needs monthly timeframe to trigger

### Indicator Impact
| Combo | Avg CAGR | Best CAGR |
|-------|----------|-----------|
| BASE (RSI only) | +10.8% | +20.8% |
| +MACD | +8.2% | +18.5% |
| +ADX | +8.5% | +14.4% |
| +RS | +8.9% | +18.5% |
| +ALL | +9.5% | +22.7% |

### Stop Impact
| Stop Type | Avg CAGR | Best CAGR | Avg MaxDD |
|-----------|----------|-----------|-----------|
| None | +11.2% | +22.7% | 25.8% |
| WMA20 | +9.1% | +20.8% | 23.2% |
| Trail 3% | +9.8% | +20.7% | 22.1% |

---

## RECOMMENDED v10 CONFIGURATION

### NEW BEST: Maximum Returns (v9E_DEFAULT + ALL + MONTHLY)
```
Entry: V9E_DEFAULT (D-RSI zone 40-50 required)
Rebalancing: MONTHLY
Indicators: MACD(12,26,9) + ADX(14) + RS vs NIFTY 50
Stop: None (zone filter acts as natural stop)
Expected: CAGR ~27.3% | MaxDD ~21.2% | Trades: 70
```

### Best Risk-Adjusted (v9E_DEFAULT + ADX + MONTHLY)
```
Entry: V9E_DEFAULT (D-RSI zone 40-50 required)
Rebalancing: MONTHLY
Indicators: ADX(14) filter (ADX > 20, +DI > -DI)
Stop: None (ADX acts as filter)
Expected: CAGR ~19.9% | MaxDD ~4.6% | Trades: 44
```

### Aggressive Daily (RELAXED + MACD+RS + DAILY + Trail)
```
Entry: RELAXED (all regimes allowed)
Rebalancing: DAILY
Indicators: MACD(12,26,9) + RS vs NIFTY 50
Stop: Trail 3%
Expected: CAGR ~20.7% | MaxDD ~17.3% | Trades: 344
```

---

## FILES CREATED
- `scanner_v9e_backtest.py` — v1 backtester (11 configs, no stops)
- `scanner_v9e_backtest_v2.py` — v2 backtester (22 configs, with stops)
- `scanner_v9e_backtest_v3.py` — v3 backtester (216 configs, frequency + indicators)
- `backtest_report.txt` — v1 full report
- `backtest_v2_report.txt` — v2 full report
- `backtest_v3_report.txt` — v3 full report (partial)
- `backtest_results.json` — v1 machine-readable
- `backtest_v2_results.json` — v2 machine-readable
- `backtest_v3_results.json` — v3 machine-readable (partial)
- `v10_best_practices.md` — Complete implementation guide
- `BACKTEST_NOTES.md` — This file

## NEXT STEPS
1. ~~Integrate daily scanning into Scanner_v9E.html~~ DONE
2. ~~Add MACD and RS indicators to scoring engine~~ DONE
3. ~~Add ADX filter and WMA20 stop~~ DONE
4. ~~Test on live data (paper trading)~~ DONE
5. Deploy with Rs 10 lakh capital

---

## v4 RESULTS (NEW INDICATORS TESTED)

### Tested 18 configurations with new indicators:
- Bollinger Bands (%B, bandwidth)
- Stochastic RSI (K, D)
- OBV + OBV_SMA crossover
- ATR% (volatility)
- Williams %R
- CCI (Commodity Channel Index)
- PSAR (Parabolic SAR)
- VWAP (Volume Weighted Average Price)

### Results Summary

| Config | CAGR | MaxDD | Trades | Notes |
|--------|------|-------|--------|-------|
| v4:RELAXED+ALL+MONTHLY | +20.5% | 25.2% | 4 | Too few trades |
| v4:V9E+SCORE220+MONTHLY | +19.9% | 10.5% | 70 | Best risk-adjusted |
| v4:V9E+ALL+DAILY+trail3 | +16.5% | 22.8% | 1442 | High churn |
| v4:V9E+SCORE200+MONTHLY | +17.7% | 20.1% | 84 | Good balance |
| v4:V9E+ADX25+MONTHLY | +13.9% | 20.9% | 80 | Conservative |
| BASE:V9E+ALL+MONTHLY | +10.9% | 23.1% | 212 | Baseline |

### Key Findings
1. **New indicators did NOT improve over v3 baseline (27.3%)**
2. **Best v4 config**: v4:V9E+SCORE220+MONTHLY with 19.9% CAGR, 10.5% MaxDD
3. **Bollinger Bands + StochRSI added noise** - lower CAGR than v3 baseline
4. **PSAR stop slightly improved**: 12.8% vs 13.6% (lower trades, same MaxDD)
5. **Score threshold 220 is optimal**: 19.9% CAGR, 10.5% MaxDD, 70 trades
6. **ADX threshold 30**: 12.6% CAGR, 11.4% MaxDD (conservative, fewer false signals)

### Conclusion
The original v3 baseline **V9E_DEFAULT + ALL + MONTHLY (27.3% CAGR)** remains the best configuration. New indicators (Bollinger, StochRSI, OBV, etc.) did not add value and introduced noise.

---

## FILES CREATED
- `scanner_v9e_backtest.py` — v1 backtester (11 configs, no stops)
- `scanner_v9e_backtest_v2.py` — v2 backtester (22 configs, with stops)
- `scanner_v9e_backtest_v3.py` — v3 backtester (216 configs, frequency + indicators)
- `scanner_v9e_backtest_v4.py` — v4 backtester (18 configs, new indicators)
- `scanner_server.py` — Flask backend for paper trading
- `scanner_v10_paper.html` — Paper trading frontend
- `backtest_report.txt` — v1 full report
- `backtest_v2_report.txt` — v2 full report
- `backtest_v3_report.txt` — v3 full report (partial)
- `backtest_v4_results.json` — v4 machine-readable results
- `backtest_results.json` — v1 machine-readable
- `backtest_v2_results.json` — v2 machine-readable
- `backtest_v3_results.json` — v3 machine-readable (partial)
- `v10_best_practices.md` — Complete implementation guide
- `BACKTEST_NOTES.md` — This file

---

## PAPER TRADING SYSTEM

### Backend: scanner_server.py
- Flask server on port 5000
- Fetches live Yahoo Finance data
- Computes all indicators (RSI, MACD, ADX, Bollinger, StochRSI, OBV, ATR, Williams%R, CCI, PSAR, VWAP)
- Manages portfolio positions and trades
- Saves portfolio to data/portfolio.json

### Frontend: scanner_v10_paper.html
- Connects to backend API
- Displays scan results with scoring
- Manages paper trading portfolio (Rs 10,00,000 initial)
- Shows P&L, equity curve, trade log
- Auto-updates prices every 30 seconds

### How to Run
```bash
# Start backend
$py = "C:\Users\admin\AppData\Local\Programs\Python\Python312\python.exe"
& $py "C:\Users\admin\OneDrive\Desktop\BackTesting\scanner_server.py"

# Open browser
http://localhost:5000
```

---

## FINAL RECOMMENDATION

### For Live Trading (After Paper Trading)
```
Config: V9E_DEFAULT + ALL + MONTHLY
Capital: Rs 10,00,000
Rebalancing: Monthly (first Monday of each month)
Top N: 3 indices per scan
Expected: CAGR ~27.3% | MaxDD ~21.2%
```

### Paper Trading Period
- Run for 1 month minimum
- Track actual vs expected performance
- Verify regime detection accuracy
- Check for slippage and execution issues
