"""
Run remaining v3 configs (118-216) in batches of 10
"""
import json
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from scanner_v9e_backtest_v3 import *

BATCH_SIZE = 10
START_CONFIG = 118
END_CONFIG = 216

def main():
    print("=" * 60)
    print(f"RUNNING REMAINING CONFIGS: {START_CONFIG} to {END_CONFIG}")
    print(f"Batch size: {BATCH_SIZE}")
    print("=" * 60)
    
    # Load existing results
    existing_results = []
    if os.path.exists("backtest_v3_results.json"):
        with open("backtest_v3_results.json", "r") as f:
            existing_results = json.load(f)
        print(f"Loaded {len(existing_results)} existing results")
    
    # Download data
    print("\nDownloading data...")
    all_data = {}
    for name, ticker in SYMBOLS.items():
        try:
            df = yf.download(ticker, start=START, end=END, progress=False, auto_adjust=True)
            if df is not None and len(df) > 50:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                all_data[name] = df
        except Exception as e:
            pass
    print(f"Downloaded {len(all_data)} indices")
    
    # Add indicators
    for name in list(all_data.keys()):
        try:
            all_data[name] = add_indicators(all_data[name])
        except:
            del all_data[name]
    
    # Define configs
    base_entry = [
        ("RELAXED",        {"entry_mode": "relaxed", "min_score": 120, "require_ha_band": False}),
        ("REGIME_A",       {"entry_mode": "regime_a", "min_score": 120, "require_ha_band": False}),
        ("V9E_DEFAULT",    {"entry_mode": "v9e_default", "min_score": 160, "require_ha_band": True}),
    ]
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
    rebal_freqs = ["daily", "biweekly", "monthly"]
    stops = ["none", "wma20", "trail_3"]
    
    # Generate all configs
    all_configs = []
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
                    all_configs.append((name, params, freq))
    
    # Run configs in batches
    new_results = []
    for batch_start in range(START_CONFIG - 1, END_CONFIG, BATCH_SIZE):
        batch_end = min(batch_start + BATCH_SIZE, END_CONFIG)
        print(f"\n{'='*60}")
        print(f"BATCH: Configs {batch_start + 1} to {batch_end}")
        print(f"{'='*60}")
        
        for i in range(batch_start, batch_end):
            if i >= len(all_configs):
                break
            name, params, freq = all_configs[i]
            print(f"\nConfig {i+1}: {name}")
            
            try:
                r = backtest(all_data, params, freq, CAPITAL, TOP_N)
                if r:
                    r["config_name"] = name
                    r["config_params"] = params
                    r["rebal_freq"] = freq
                    new_results.append(r)
                    print(f"  CAGR: {r['cagr_pct']:+.1f}% | MaxDD: {r['max_drawdown_pct']:.1f}% | Trades: {r['total_trades']}")
            except Exception as e:
                print(f"  ERROR: {e}")
    
    # Merge results
    all_results = existing_results + new_results
    all_results.sort(key=lambda x: x["cagr_pct"], reverse=True)
    
    # Save
    with open("backtest_v3_results.json", "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    
    print(f"\n\n{'='*60}")
    print("NEW RESULTS FROM BATCHES 118-216")
    print(f"{'='*60}")
    for r in sorted(new_results, key=lambda x: x["cagr_pct"], reverse=True)[:10]:
        print(f"{r['config_name']:<50} CAGR: {r['cagr_pct']:+.1f}% | MaxDD: {r['max_drawdown_pct']:.1f}%")
    
    print(f"\nTotal configs now: {len(all_results)}")

if __name__ == "__main__":
    main()
