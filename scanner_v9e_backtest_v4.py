"""
Scanner v9E Backtest v4 - NEW INDICATORS
Baseline: V9E_DEFAULT + ALL + MONTHLY = 27.3%% CAGR, 21.2%% MaxDD
"""
import json, os, warnings
from datetime import datetime
import numpy as np
import pandas as pd
import yfinance as yf
warnings.filterwarnings("ignore")

SYMBOLS = {
    "NIFTY 50": "^NSEI", "NIFTY BANK": "^NSEBANK", "NIFTY IT": "^CNXIT",
    "NIFTY AUTO": "^CNXAUTO", "NIFTY PHARMA": "^CNXPHARMA", "NIFTY FMCG": "^CNXFMCG",
    "NIFTY METAL": "^CNXMETAL", "NIFTY REALTY": "^CNXREALTY", "NIFTY ENERGY": "^CNXENERGY",
    "NIFTY PSU BANK": "^CNXPSUBANK", "NIFTY MNC": "^CNXMNC",
}
START, END, CAPITAL, TOP_N, COMMISSION_PCT = "2021-01-01", "2026-06-15", 1000000, 3, 0.05

def rsi_wilder(s, p):
    d=s.diff(); g=d.clip(lower=0); l=(-d).clip(lower=0)
    ag=g.ewm(alpha=1/p,min_periods=p).mean(); al=l.ewm(alpha=1/p,min_periods=p).mean()
    return 100-(100/(1+ag/al))

def wma(s, p):
    w=np.arange(1,p+1); return s.rolling(p).apply(lambda x:np.dot(x,w)/w.sum(),raw=True)

def ema(s, p): return s.ewm(span=p,adjust=False).mean()

def compute_macd(c):
    ef=ema(c,12); es=ema(c,26); ml=ef-es; sl=ema(ml,9); return ml,sl,ml-sl

def compute_adx(h,l,c,p=14):
    pdm=h.diff(); mdm=-l.diff()
    pdm[pdm<0]=0; mdm[mdm<0]=0; pdm[pdm<mdm]=0; mdm[mdm<pdm]=0
    tr=pd.concat([h-l,abs(h-c.shift()),abs(l-c.shift())],axis=1).max(axis=1)
    atr=tr.ewm(alpha=1/p,min_periods=p).mean()
    pdi=100*(pdm.ewm(alpha=1/p,min_periods=p).mean()/atr)
    mdi=100*(mdm.ewm(alpha=1/p,min_periods=p).mean()/atr)
    dx=100*abs(pdi-mdi)/(pdi+mdi+1e-10); adx=dx.ewm(alpha=1/p,min_periods=p).mean()
    return adx,pdi,mdi

def compute_bollinger(c,p=20,sd=2):
    m=c.rolling(p).mean(); s=c.rolling(p).std()
    u=m+s*sd; lo=m-s*sd; pb=(c-lo)/(u-lo+1e-10); bw=(u-lo)/(m+1e-10)
    return u,m,lo,pb,bw

def compute_stoch_rsi(c,rp=14,sp=14,kp=3,dp=3):
    r=rsi_wilder(c,rp); sr=(r-r.rolling(sp).min())/(r.rolling(sp).max()-r.rolling(sp).min()+1e-10)
    k=sr.rolling(kp).mean()*100; d=k.rolling(dp).mean(); return k,d

def compute_obv(c,v):
    o=pd.Series(0.0,index=c.index)
    for i in range(1,len(c)):
        if c.iloc[i]>c.iloc[i-1]: o.iloc[i]=o.iloc[i-1]+v.iloc[i]
        elif c.iloc[i]<c.iloc[i-1]: o.iloc[i]=o.iloc[i-1]-v.iloc[i]
        else: o.iloc[i]=o.iloc[i-1]
    return o,o.rolling(20).mean()

def compute_atr(h,l,c,p=14):
    tr=pd.concat([h-l,abs(h-c.shift()),abs(l-c.shift())],axis=1).max(axis=1)
    atr=tr.ewm(alpha=1/p,min_periods=p).mean(); return atr,atr/c*100

def compute_wr(h,l,c,p=14):
    return -100*(h.rolling(p).max()-c)/(h.rolling(p).max()-l.rolling(p).min()+1e-10)

def compute_cci(h,l,c,p=20):
    tp=(h+l+c)/3; sma=tp.rolling(p).mean()
    mad=tp.rolling(p).apply(lambda x:np.abs(x-x.mean()).mean(),raw=True)
    return (tp-sma)/(0.015*mad+1e-10)

def compute_psar(h,l,c,af0=0.02,afs=0.02,afm=0.2):
    n=len(c); ps=pd.Series(0.0,index=c.index); af=af0; bull=True
    hp=h.iloc[0]; lp=l.iloc[0]; ps.iloc[0]=hp
    for i in range(1,n):
        if bull:
            ps.iloc[i]=ps.iloc[i-1]+af*(hp-ps.iloc[i-1])
            if l.iloc[i]<ps.iloc[i]: bull=False; ps.iloc[i]=hp; lp=l.iloc[i]; af=af0
            elif h.iloc[i]>hp: hp=h.iloc[i]; af=min(af+afs,afm)
        else:
            ps.iloc[i]=ps.iloc[i-1]+af*(lp-ps.iloc[i-1])
            if h.iloc[i]>ps.iloc[i]: bull=True; ps.iloc[i]=lp; hp=h.iloc[i]; af=af0
            elif l.iloc[i]<lp: lp=l.iloc[i]; af=min(af+afs,afm)
    return ps

def compute_vwap(h,l,c,v,p=20):
    tp=(h+l+c)/3; return (tp*v).rolling(p).sum()/v.rolling(p).sum()

def add_indicators(df):
    c=df["Close"]; h=df["High"]; l=df["Low"]; v=df["Volume"]
    df["RSI4"]=rsi_wilder(c,4); df["RSI8"]=rsi_wilder(c,8); df["RSI14"]=rsi_wilder(c,14)
    df["WMA20"]=wma(c,20); df["WMA50"]=wma(c,50)
    df["MACD"],df["MACD_signal"],df["MACD_hist"]=compute_macd(c)
    df["ADX"],df["PlusDI"],df["MinusDI"]=compute_adx(h,l,c)
    df["ATR"],df["ATR_pct"]=compute_atr(h,l,c)
    df["BB_upper"],df["BB_mid"],df["BB_lower"],df["BB_pctB"],df["BB_width"]=compute_bollinger(c)
    df["StochK"],df["StochD"]=compute_stoch_rsi(c)
    df["OBV"],df["OBV_SMA"]=compute_obv(c,v)
    df["WR"]=compute_wr(h,l,c); df["CCI"]=compute_cci(h,l,c)
    df["PSAR"]=compute_psar(h,l,c); df["VWAP"]=compute_vwap(h,l,c,v)
    return df

def compute_score_v4(row, nifty_rsi14=None):
    s=0; r4=row.get("RSI4",np.nan); r8=row.get("RSI8",np.nan); r14=row.get("RSI14",np.nan)
    if np.isnan(r4) or np.isnan(r8) or np.isnan(r14): return -999
    if r4>80: s+=50
    elif r4>70: s+=40
    elif r4>60: s+=30
    elif r4>50: s+=20
    elif r4>40: s+=10
    if r8>70: s+=40
    elif r8>60: s+=30
    elif r8>50: s+=20
    elif r8>40: s+=10
    if r14>60: s+=30
    elif r14>50: s+=20
    elif r14>40: s+=10
    if r4>r8>r14: s+=20
    mh=row.get("MACD_hist",np.nan)
    if not np.isnan(mh):
        if mh>0: s+=20
        else: s-=10
    adx=row.get("ADX",np.nan); pdi=row.get("PlusDI",np.nan); mdi=row.get("MinusDI",np.nan)
    if not np.isnan(adx) and not np.isnan(pdi) and not np.isnan(mdi):
        if adx>25 and pdi>mdi: s+=25
        elif adx>20 and pdi>mdi: s+=15
        elif adx>25 and pdi<mdi: s-=15
    if nifty_rsi14 and not np.isnan(nifty_rsi14) and nifty_rsi14>0:
        rs=r14/nifty_rsi14
        if rs>1.10: s+=25
        elif rs>1.05: s+=15
        elif rs>1.00: s+=5
    bb=row.get("BB_pctB",np.nan)
    if not np.isnan(bb):
        if bb<0.2: s+=20
        elif bb<0.4: s+=10
        elif bb>0.8: s-=10
        elif bb>0.9: s-=20
    sk=row.get("StochK",np.nan); sd=row.get("StochD",np.nan)
    if not np.isnan(sk) and not np.isnan(sd):
        if sk>sd and sk<30: s+=25
        elif sk>sd: s+=10
        elif sk<sd and sk>70: s-=20
    obv=row.get("OBV",np.nan); os=row.get("OBV_SMA",np.nan)
    if not np.isnan(obv) and not np.isnan(os):
        if obv>os: s+=10
        else: s-=5
    wr=row.get("WR",np.nan)
    if not np.isnan(wr):
        if wr>-20: s+=15
        elif wr>-50: s+=5
        elif wr<-80: s-=10
    ci=row.get("CCI",np.nan)
    if not np.isnan(ci):
        if ci>100: s+=15
        elif ci>0: s+=5
        elif ci<-100: s-=15
    pr=row.get("Close",np.nan); ps=row.get("PSAR",np.nan)
    if not np.isnan(pr) and not np.isnan(ps):
        if pr>ps: s+=10
        else: s-=10
    vw=row.get("VWAP",np.nan)
    if not np.isnan(pr) and not np.isnan(vw):
        if pr>vw: s+=10
        else: s-=5
    ap=row.get("ATR_pct",np.nan)
    if not np.isnan(ap):
        if ap<1.5: s+=10
        elif ap>3.0: s-=10
    return s

def classify_regime(row):
    r4=row.get("RSI4",np.nan); r8=row.get("RSI8",np.nan); r14=row.get("RSI14",np.nan)
    w20=row.get("WMA20",np.nan); p=row.get("Close",np.nan)
    if np.isnan(r4) or np.isnan(r8) or np.isnan(r14): return "C"
    aw=p>w20 if not np.isnan(w20) else True
    if r4>60 and r8>55 and r14>50 and aw: return "A"
    elif r4<40 and r8<45 and r14<50: return "C"
    else: return "B"

def get_rebalance_dates(dates, freq):
    if freq=="daily": return list(dates)
    elif freq=="monthly":
        rb=[]; cm=None
        for d in dates:
            m=(d.year,d.month)
            if cm is not None and m!=cm: rb.append(pd)
            cm=m; pd=d
        rb.append(dates[-1]); return rb
    elif freq=="biweekly":
        rb=[]; ct=0
        for i,d in enumerate(dates):
            if i==0: continue
            pd2=dates[i-1]; ct+=(d-pd2).days
            if ct>=10: rb.append(pd2); ct=0
        rb.append(dates[-1]); return rb
    return list(dates)

def backtest(data, config, rebal_freq, capital, top_n):
    entry_mode=config.get("entry_mode","v9e_default")
    min_score=config.get("min_score",150)
    stop_type=config.get("stop_type","none")
    use_new=config.get("use_new_indicators",True)
    min_adx=config.get("min_adx",20)
    cash=capital; positions={}; trades=[]; eq=[]; pp={}
    n50d=data.get("NIFTY 50"); n50r=n50d["RSI14"] if n50d is not None else None
    ad=sorted(set().union(*[set(d.index) for d in data.values() if d is not None]))
    rd=get_rebalance_dates(ad, rebal_freq)
    for dt in rd:
        for nm,po in list(positions.items()):
            if nm in data and data[nm] is not None and dt in data[nm].index:
                cp=data[nm].loc[dt,"Close"]
                if nm not in pp or cp>pp[nm]: pp[nm]=cp
        for nm in list(positions.keys()):
            if nm not in data or data[nm] is None or dt not in data[nm].index: continue
            po=positions[nm]; cp=data[nm].loc[dt,"Close"]; sell=False; reason=""
            if stop_type=="wma20":
                w=data[nm].loc[dt,"WMA20"]
                if not np.isnan(w) and cp<w: sell=True; reason="WMA20 stop"
            elif stop_type.startswith("trail_"):
                pct=float(stop_type.split("_")[1])/100; pk=pp.get(nm,po["buy_price"])
                if cp<pk*(1-pct): sell=True; reason=f"Trail {pct*100:.1f}%"
            elif stop_type=="psar":
                ps2=data[nm].loc[dt,"PSAR"]
                if not np.isnan(ps2) and cp<ps2: sell=True; reason="PSAR reversal"
            if sell:
                ret=(cp-po["buy_price"])/po["buy_price"]*100
                comm=cp*po["shares"]*COMMISSION_PCT/100; pr=cp*po["shares"]-comm
                cash+=pr; trades.append({"date":dt,"action":"SELL","name":nm,"price":cp,"shares":po["shares"],"buy_date":po["buy_date"],"buy_price":po["buy_price"],"reason":reason,"return_pct":ret,"proceeds":pr})
                del positions[nm]; pp.pop(nm,None)
        for nm in list(positions.keys()):
            if nm not in data or data[nm] is None or dt not in data[nm].index: continue
            po=positions[nm]; cp=data[nm].loc[dt,"Close"]; rg=classify_regime(data[nm].loc[dt])
            if entry_mode=="relaxed": pass
            elif entry_mode in ["regime_a","v9e_default"]:
                if rg!="A":
                    ret=(cp-po["buy_price"])/po["buy_price"]*100; comm=cp*po["shares"]*COMMISSION_PCT/100; pr=cp*po["shares"]-comm
                    cash+=pr; trades.append({"date":dt,"action":"SELL","name":nm,"price":cp,"shares":po["shares"],"buy_date":po["buy_date"],"buy_price":po["buy_price"],"reason":f"Regime {rg} exit","return_pct":ret,"proceeds":pr})
                    del positions[nm]; pp.pop(nm,None)
        scs={}
        for nm,df in data.items():
            if df is None or dt not in df.index or nm in positions: continue
            row=df.loc[dt]; nr=None
            if n50r is not None and dt in n50r.index: nr=n50r.loc[dt]
            sc=compute_score_v4(row,nr); scs[nm]=sc
            if sc<min_score: del scs[nm]; continue
            if use_new:
                adx=row.get("ADX",np.nan)
                if not np.isnan(adx) and adx<min_adx: del scs[nm]
        ranked=sorted(scs.items(),key=lambda x:x[1],reverse=True)[:top_n]
        alloc=cash/len(ranked) if ranked else 0
        for nm,sc in ranked:
            pr2=data[nm].loc[dt,"Close"]
            if pr2<=0 or alloc<=0: continue
            sh=alloc/pr2; comm=alloc*COMMISSION_PCT/100; cash-=(alloc+comm)
            positions[nm]={"shares":sh,"buy_price":pr2,"buy_date":dt}; pp[nm]=pr2
            trades.append({"date":dt,"action":"BUY","name":nm,"price":pr2,"shares":sh,"buy_date":dt,"buy_price":pr2,"reason":f"Score:{sc:.0f}","return_pct":0,"proceeds":0})
        pv=cash
        for nm,po in positions.items():
            if nm in data and data[nm] is not None and dt in data[nm].index: pv+=data[nm].loc[dt,"Close"]*po["shares"]
            else: pv+=po["buy_price"]*po["shares"]
        eq.append({"date":dt,"equity":pv})
    fd=ad[-1]
    for nm in list(positions.keys()):
        po=positions[nm]
        if nm in data and data[nm] is not None and fd in data[nm].index: cp2=data[nm].loc[fd,"Close"]
        else: cp2=po["buy_price"]
        ret=(cp2-po["buy_price"])/po["buy_price"]*100; comm=cp2*po["shares"]*COMMISSION_PCT/100; pr=cp2*po["shares"]-comm
        cash+=pr; trades.append({"date":fd,"action":"SELL","name":nm,"price":cp2,"shares":po["shares"],"buy_date":po["buy_date"],"buy_price":po["buy_price"],"reason":"Final","return_pct":ret,"proceeds":pr})
    edf=pd.DataFrame(eq)
    if len(edf)<2: return None
    edf["date"]=pd.to_datetime(edf["date"]); edf=edf.set_index("date")
    tr=(cash-capital)/capital*100; yrs=(edf.index[-1]-edf.index[0]).days/365.25
    cagr=((cash/capital)**(1/yrs)-1)*100 if yrs>0 else 0
    rm=edf["equity"].cummax(); dd=(edf["equity"]-rm)/rm*100; mdd=dd.min()
    st=[t for t in trades if t["action"]=="SELL" and t["reason"]!="Final"]
    w=[t for t in st if t["return_pct"]>0]; wr=len(w)/len(st)*100 if st else 0
    aw=np.mean([t["return_pct"] for t in w]) if w else 0
    lo=[t for t in st if t["return_pct"]<=0]; al=np.mean([t["return_pct"] for t in lo]) if lo else 0
    return {"final_value":round(cash),"total_return_pct":round(tr,2),"cagr_pct":round(cagr,2),"max_drawdown_pct":round(abs(mdd),2),"win_rate_pct":round(wr,1),"avg_win_pct":round(aw,2),"avg_loss_pct":round(al,2),"total_trades":len(trades),"sell_trades":len(st),"trades":trades,"equity":eq}

def main():
    print("="*60)
    print("SCANNER v9E BACKTEST v4 - NEW INDICATORS")
    print("="*60)
    print(f"Period: {START} - {END} | Capital: Rs {CAPITAL:,}")
    print()
    print("STEP 1: Downloading data...")
    ad={}
    for nm,tk in SYMBOLS.items():
        try:
            df=yf.download(tk,start=START,end=END,progress=False,auto_adjust=True)
            if df is not None and len(df)>50:
                if isinstance(df.columns,pd.MultiIndex): df.columns=df.columns.get_level_values(0)
                ad[nm]=df; print(f"  OK: {nm} -> {len(df)} days")
        except: pass
    print(f"\n  Downloaded: {len(ad)} indices")
    print("\nSTEP 2: Computing indicators...")
    for nm in list(ad.keys()):
        try: ad[nm]=add_indicators(ad[nm]); print(f"  OK: {nm}")
        except Exception as e: print(f"  FAIL: {nm}: {e}"); del ad[nm]
    configs=[
        ("BASE:V9E+ALL+MONTHLY",{"entry_mode":"v9e_default","min_score":150,"stop_type":"none","use_new_indicators":False},"monthly"),
        ("BASE:V9E+ADX+MONTHLY",{"entry_mode":"v9e_default","min_score":150,"stop_type":"none","use_new_indicators":False,"min_adx":20},"monthly"),
        ("v4:V9E+ALL+MONTHLY",{"entry_mode":"v9e_default","min_score":150,"stop_type":"none","use_new_indicators":True},"monthly"),
        ("v4:V9E+ALL+MONTHLY+PSAR",{"entry_mode":"v9e_default","min_score":150,"stop_type":"psar","use_new_indicators":True},"monthly"),
        ("v4:V9E+ALL+MONTHLY+trail3",{"entry_mode":"v9e_default","min_score":150,"stop_type":"trail_3","use_new_indicators":True},"monthly"),
        ("v4:V9E+ALL+MONTHLY+WMA20",{"entry_mode":"v9e_default","min_score":150,"stop_type":"wma20","use_new_indicators":True},"monthly"),
        ("v4:V9E+ALL+DAILY",{"entry_mode":"v9e_default","min_score":150,"stop_type":"none","use_new_indicators":True},"daily"),
        ("v4:V9E+ALL+DAILY+PSAR",{"entry_mode":"v9e_default","min_score":150,"stop_type":"psar","use_new_indicators":True},"daily"),
        ("v4:V9E+ALL+DAILY+trail3",{"entry_mode":"v9e_default","min_score":150,"stop_type":"trail_3","use_new_indicators":True},"daily"),
        ("v4:RELAXED+ALL+MONTHLY",{"entry_mode":"relaxed","min_score":150,"stop_type":"none","use_new_indicators":True},"monthly"),
        ("v4:RELAXED+ALL+DAILY",{"entry_mode":"relaxed","min_score":150,"stop_type":"none","use_new_indicators":True},"daily"),
        ("v4:RELAXED+ALL+DAILY+PSAR",{"entry_mode":"relaxed","min_score":150,"stop_type":"psar","use_new_indicators":True},"daily"),
        ("v4:V9E+SCORE180+MONTHLY",{"entry_mode":"v9e_default","min_score":180,"stop_type":"none","use_new_indicators":True},"monthly"),
        ("v4:V9E+SCORE200+MONTHLY",{"entry_mode":"v9e_default","min_score":200,"stop_type":"none","use_new_indicators":True},"monthly"),
        ("v4:V9E+SCORE220+MONTHLY",{"entry_mode":"v9e_default","min_score":220,"stop_type":"none","use_new_indicators":True},"monthly"),
        ("v4:V9E+SCORE250+MONTHLY",{"entry_mode":"v9e_default","min_score":250,"stop_type":"none","use_new_indicators":True},"monthly"),
        ("v4:V9E+ADX25+MONTHLY",{"entry_mode":"v9e_default","min_score":150,"stop_type":"none","use_new_indicators":True,"min_adx":25},"monthly"),
        ("v4:V9E+ADX30+MONTHLY",{"entry_mode":"v9e_default","min_score":150,"stop_type":"none","use_new_indicators":True,"min_adx":30},"monthly"),
    ]
    print(f"\nSTEP 3: Running {len(configs)} configurations...")
    results=[]
    for i,(nm,pr,fq) in enumerate(configs):
        print(f"\n{'='*60}\nCONFIG {i+1}/{len(configs)} {nm}\n{'='*60}")
        try:
            r=backtest(ad,pr,fq,CAPITAL,TOP_N)
            if r:
                r["config_name"]=nm; r["config_params"]=pr; r["rebal_freq"]=fq; results.append(r)
                print(f"  CAGR: {r['cagr_pct']:+.1f}% | MaxDD: {r['max_drawdown_pct']:.1f}% | Trades: {r['total_trades']}")
        except Exception as e: print(f"  ERROR: {e}")
    results.sort(key=lambda x:x["cagr_pct"],reverse=True)
    print(f"\n{'='*60}\nFINAL RESULTS\n{'='*60}")
    print(f"{'Config':<45} {'CAGR':>7} {'MaxDD':>7} {'Win%':>5} {'Trd':>4}")
    print("-"*70)
    for r in results:
        m=" <-- BEST" if r==results[0] else (" <-- WORST" if r==results[-1] else "")
        print(f"{r['config_name']:<45} {r['cagr_pct']:>+6.1f}% {r['max_drawdown_pct']:>6.1f}% {r['win_rate_pct']:>4.0f}% {r['total_trades']:>4}{m}")
    with open("backtest_v4_results.json","w") as f: json.dump(results,f,indent=2,default=str)
    print(f"\nBest: {results[0]['config_name']} | CAGR: {results[0]['cagr_pct']:+.1f}% | MaxDD: {results[0]['max_drawdown_pct']:.1f}%")
    print(f"Reports saved: backtest_v4_results.json")

if __name__=="__main__": main()
