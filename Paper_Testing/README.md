# Scanner v10 - Paper Trading PWA

NSE Index Scanner with Paper Trading. **Same data source as Scanner_v9E.html** - fetches directly from NSE India via CORS proxies.

## Data Source
- **Live prices**: NSE India API (`https://www.nseindia.com/api/allIndices`)
- **Historical**: NSE CSV archives (`https://archives.nseindia.com/content/indices/ind_close_all_YYYYMMDD.csv`)
- **Proxies**: `cors-proxy-xi-ten.vercel.app` → `corsproxy.io` → `api.allorigins.win`
- Fetches 139 NSE indices directly in browser

## Backtested Performance
- **CAGR**: 27.3%
- **Max Drawdown**: 21.2%
- **Win Rate**: 51%
- **Trades**: 70 (monthly rebalancing)

## Config
- Entry: V9E_DEFAULT (D-RSI zone 40-50)
- Rebalancing: MONTHLY
- Indicators: RSI(4,8,14) + MACD(12,26,9) + ADX(14)
- Capital: Rs 10,00,000
- Top N: 3 indices per scan

## Quick Start
Just open `index.html` in any browser. No backend needed.

## PWA Features
- Installable as app (Add to Home Screen)
- Offline mode with cached data
- Works on mobile + desktop
- Same CORS proxy chain as Scanner_v9E.html

## Files
| File | Description |
|------|-------------|
| `index.html` | Main PWA (fetches NSE directly) |
| `manifest.json` | PWA manifest |
| `service-worker.js` | Offline caching for NSE data |
| `offline.html` | Offline fallback |
| `icon-192.svg` | App icon |
| `icon-512.svg` | App icon large |
| `README.md` | This file |
