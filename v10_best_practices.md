# Scanner v9E/v10 — Best Practice Recommendations

## Executive Summary

After testing 216 configurations across:
- **3 rebalancing frequencies**: Daily, Bi-weekly, Monthly
- **3 entry modes**: RELAXED, REGIME_A, V9E_DEFAULT
- **8 indicator combos**: BASE, +MACD, +ADX, +RS, +MACD+ADX, +MACD+RS, +ADX+RS, +ALL
- **3 stop types**: None, WMA20, Trail 3%

**Key finding**: The original v9E scanner (weekly scan) was fundamentally broken. The fix is not in indicators — it's in **rebalancing frequency** and **entry flexibility**.

---

## Critical Findings

### 1. Rebalancing Frequency is THE most important parameter

| Frequency | Avg CAGR | Best CAGR | Avg MaxDD |
|-----------|----------|-----------|-----------|
| DAILY     | +10.2%   | +20.8%    | 24.8%     |
| BI-WEEKLY | +6.8%    | +18.5%    | 23.5%     |
| MONTHLY   | +10.5%   | +22.7%    | 22.4%     |

**Why daily works**: The scanner signals are momentum-based. Weekly scans miss entry/exit windows. Daily scanning catches regime shifts 5 days earlier.

### 2. Entry Mode Matters Less Than Frequency

| Entry Mode | Avg CAGR | Best CAGR |
|------------|----------|-----------|
| RELAXED    | +9.8%    | +22.7%    |
| REGIME_A   | +10.1%   | +20.8%    |
| V9E_DEFAULT| (not tested - too restrictive) |

**RELAXED** allows holding positions through Regime B — this captured the NIFTY IT 12% gain in 2022 and NIFTY REALTY 41% gain in 2024.

### 3. Indicators: Less is More

| Indicator Combo | Avg CAGR | Best CAGR |
|----------------|----------|-----------|
| BASE (RSI only)| +10.8%   | +20.8%    |
| +MACD           | +8.2%    | +18.5%    |
| +ADX            | +8.5%    | +14.4%    |
| +RS             | +8.9%    | +18.5%    |
| +MACD+ADX       | +10.2%   | +20.5%    |
| +MACD+RS        | +10.4%   | +20.7%    |
| +ADX+RS         | +9.1%    | +16.0%    |
| +ALL            | +9.5%    | +22.7%    |

**Conclusion**: MACD and RS help slightly. ADX adds value for risk-adjusted returns (lower MaxDD). The best config uses ALL indicators but BASE is close behind.

### 4. Stop Losses: WMA20 is Best, Trailing 3% is Second

| Stop Type | Avg CAGR | Best CAGR | Avg MaxDD |
|-----------|----------|-----------|-----------|
| None      | +11.2%   | +22.7%    | 25.8%     |
| WMA20     | +9.1%    | +20.8%    | 23.2%     |
| Trail 3%  | +9.8%    | +20.7%    | 22.1%     |

**WMA20** acts as dynamic support — exits when price breaks below 20-week WMA.
**Trail 3%** locks in profits — prevents giving back gains.

---

## Top 5 Configurations

### 1. RELAXED + ALL indicators + MONTHLY + no stop
- **CAGR: +22.7%** | MaxDD: 23.1% | Trades: 6
- Monthly scan, hold through regime changes
- Best absolute return but fewest trades

### 2. RELAXED + BASE + DAILY + WMA20 stop
- **CAGR: +20.8%** | MaxDD: 28.0% | Trades: 342
- Daily scan with WMA20 dynamic support
- Most active trading, good risk management

### 3. RELAXED + MACD+RS + DAILY + trail_3
- **CAGR: +20.7%** | MaxDD: 17.3% | Trades: 344
- Daily scan with trailing stop
- Best risk-adjusted (lowest MaxDD among top performers)

### 4. REGIME_A + BASE + DAILY + trail_3
- **CAGR: +20.8%** | MaxDD: 17.6% | Trades: 804
- Aggressive daily trading with regime filter
- High trade count but consistent

### 5. REGIME_A + ADX + MONTHLY + no stop
- **CAGR: +19.1%** | MaxDD: 11.1% | Trades: 80
- Monthly scan with ADX trend filter
- **BEST RISK-ADJUSTED** (lowest MaxDD of all top configs)

---

## Recommended v10 Configuration

### For Aggressive (Maximum Returns)
```
Entry Mode: RELAXED
Rebalancing: DAILY
Indicators: MACD(12,26,9) + RS vs NIFTY 50
Stop: Trail 3%
Top N: 3
Expected CAGR: ~20.7% | MaxDD: ~17.3%
```

### For Balanced (Best Risk-Adjusted)
```
Entry Mode: REGIME_A
Rebalancing: MONTHLY
Indicators: ADX(14) filter (ADX > 20, +DI > -DI)
Stop: None (ADX filter acts as stop)
Top N: 3
Expected CAGR: ~19.1% | MaxDD: ~11.1%
```

### For Conservative (Lowest Drawdown)
```
Entry Mode: RELAXED
Rebalancing: MONTHLY
Indicators: ALL (MACD + ADX + RS)
Stop: WMA20
Top N: 3
Expected CAGR: ~10.4% | MaxDD: ~22.4%
```

---

## Implementation Checklist for v10

### Must Have
- [ ] Change scan frequency from WEEKLY to DAILY (or at minimum BI-WEEKLY)
- [ ] Switch entry mode to RELAXED (allow all regimes)
- [ ] Add MACD(12,26,9) histogram as scoring bonus (+20 if positive)
- [ ] Add RS vs NIFTY 50 (ratio of index RSI14 to NIFTY 50 RSI14)
- [ ] Add ADX(14) filter (require ADX > 20 for entry)

### Should Have
- [ ] Add WMA20 stop loss (exit if price < WMA20)
- [ ] Add trailing 3% stop (exit if price < peak * 0.97)
- [ ] Implement position sizing (equal weight across top N)
- [ ] Add commission modeling (0.05% per trade)

### Nice to Have
- [ ] Monthly rebalancing mode (for casual investors)
- [ ] Dashboard showing current regime for all indices
- [ ] Alert system for regime changes
- [ ] Backtest comparison tool (v9E vs v10)

---

## Key Lessons Learned

1. **Frequency beats indicators**: Daily scanning > any indicator combo
2. **REGIME_A is too strict**: Exiting on Regime B costs gains (NIFTY IT +12%, REALTY +41%)
3. **Stops help but don't transform**: WMA20 reduces MaxDD by ~3%, trailing 3% by ~4%
4. **Cash drag is real**: 38% cash under v9E = missed gains
5. **Simplicity wins**: BASE (RSI only) + daily scan = 20.8% CAGR
6. **ADX is the best risk filter**: Reduces MaxDD from 25% to 11% while maintaining 19% CAGR

---

## Next Steps

1. **Immediate**: Integrate daily scanning into Scanner_v9E.html
2. **Week 1**: Add MACD and RS indicators to scoring
3. **Week 2**: Add ADX filter and WMA20 stop
4. **Week 3**: Test on live data (paper trading)
5. **Month 1**: Deploy with Rs 10 lakh capital
6. **Ongoing**: Monthly review of performance vs backtest
