#!/usr/bin/env python3
"""Evaluate the fixed reproducible portfolio on 2024-2025 validation."""

from __future__ import annotations
import argparse, hashlib, json, math, sys, zipfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WALLET, DAYS, FEE = 1000.0, 731, 0.00075
CORE = {"BTC/USDT:USDT", "ETH/USDT:USDT", "BNB/USDT:USDT", "XRP/USDT:USDT", "ADA/USDT:USDT", "DOGE/USDT:USDT"}

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def load(path, strategy, max_open, pair_count):
    with zipfile.ZipFile(path) as z:
        if z.testzip() is not None: raise ValueError("ZIP integrity failure")
        rs=[n for n in z.namelist() if n.endswith('.json') and not n.endswith('_config.json')]; cs=[n for n in z.namelist() if n.endswith('_config.json')]
        if len(rs)!=1 or len(cs)!=1: raise ValueError("archive inventory mismatch")
        r=json.loads(z.read(rs[0])).get('strategy',{}).get(strategy); c=json.loads(z.read(cs[0]))
    e=c.get('exchange') or {}; pairs=set(e.get('pair_whitelist') or [])
    if not (isinstance(r,dict) and r.get('timerange')=='20240101-20260101' and r.get('backtest_days')==DAYS and c.get('dry_run_wallet')==WALLET and c.get('fee')==FEE and c.get('stake_amount')==50 and c.get('max_open_trades')==max_open and c.get('trading_mode')=='futures' and c.get('margin_mode')=='isolated' and len(pairs)==pair_count and (pair_count!=6 or pairs==CORE)):
        raise ValueError(f"contract mismatch: {strategy}")
    ts=r.get('trades') or []
    if len(ts)!=r.get('total_trades'): raise ValueError("trade count mismatch")
    for t in ts:
        s=t.get('stake_amount'); lev=t.get('leverage',1.0)
        if t.get('fee_open')!=FEE or t.get('fee_close')!=FEE or not isinstance(s,(int,float)) or isinstance(s,bool) or not math.isfinite(s) or not 0<s<=65.0 or lev!=1.0: raise ValueError(f"trade contract mismatch: {strategy}")
    return ts

def pf(ts):
    g=sum(max(float(t['profit_abs']),0) for t in ts); l=-sum(min(float(t['profit_abs']),0) for t in ts)
    return g/l if l else None

def summary(ts): return {'trades':len(ts),'profit_usdt':sum(float(t['profit_abs']) for t in ts),'profit_factor':pf(ts)}

def dd(ts):
    c=defaultdict(float)
    for t in ts:c[int(t['close_timestamp'])]+=float(t['profit_abs'])
    w=peak=WALLET; m=0.0
    for k in sorted(c):w+=c[k];peak=max(peak,w);m=max(m,peak-w)
    return m/WALLET*100

def exposure(ts):
    e=defaultdict(lambda:[0,0.0])
    for t in ts:
        e[int(t['open_timestamp'])][0]+=1;e[int(t['open_timestamp'])][1]+=float(t['stake_amount']);e[int(t['close_timestamp'])][0]-=1;e[int(t['close_timestamp'])][1]-=float(t['stake_amount'])
    n=mn=0;s=ms=0.0
    for k in sorted(e):n+=e[k][0];s+=e[k][1];mn=max(mn,n);ms=max(ms,s)
    return mn,ms

def main():
    p=argparse.ArgumentParser()
    for n in ('manifest','cross','v5','v1','output'):p.add_argument('--'+n,required=True)
    a=p.parse_args(); paths={n:(ROOT/getattr(a,n)).resolve() for n in ('manifest','cross','v5','v1')}; out=(ROOT/a.output).resolve()
    if out.exists(): print('BLOCKED: output exists',file=sys.stderr);return 3
    try:
        m=json.loads(paths['manifest'].read_text());
        if m.get('status')!='FROZEN_BEFORE_VALIDATION_PNL': raise ValueError('manifest mismatch')
        for n in ('cross','v5','v1'):
            if paths[n].relative_to(ROOT).as_posix()!=m['artifacts'][n+'_validation']: raise ValueError('artifact path mismatch')
        cross=load(paths['cross'],'ProfitMaxCrossSectionalTopTwo8h',2,50);v5=load(paths['v5'],'ProfitMaxV5Asymmetric50',2,6);raw=load(paths['v1'],'DualTrendFuturesV1',1,6)
        keys={(t['pair'],int(t['open_timestamp'])) for t in v5};v1=[t for t in raw if (t['pair'],int(t['open_timestamp'])) not in keys]; selected=cross+v5+v1
        comps={'cross':summary(cross),'v5':summary(v5),'v1_unique':summary(v1)};years={y:summary([t for t in selected if str(t['close_date']).startswith(y)]) for y in ('2024','2025')};profit=sum(t['profit_abs'] for t in selected);d=dd(selected);f=pf(selected);n,s=exposure(selected);rate=len(selected)/DAYS;ret=profit/WALLET*100
        gates={'frequency_1_to_2':1<=rate<=2,'return_positive':ret>0,'pf_gte_1_30':f is not None and f>=1.3,'dd_lte_10':d<=10,'return_dd_gte_2':d>0 and ret/d>=2,'both_years_positive':all(x['profit_usdt']>0 for x in years.values()),'components_positive_pf_gte_1_05':all(x['profit_usdt']>0 and x['profit_factor'] is not None and x['profit_factor']>=1.05 for x in comps.values()),'v1_unique_gte_20':len(v1)>=20,'positions_lte_5':n<=5,'stake_lte_20pct':s<=200+1e-9}
        passed=all(gates.values());payload={'schema_version':'1.0','cycle':'profit_max_portfolio_ensemble_cycle3','status':'PASS' if passed else 'FAIL','decision':'UNLOCK_TECHNICAL_AND_CONTINUOUS_GATES' if passed else 'KEEP_OFFLINE_RESEARCH','validation_revealed':True,'live_trading_authorized':False,'profit_guaranteed':False,'metrics':{'trades':len(selected),'days':DAYS,'trades_per_day':rate,'profit_usdt':profit,'return_pct':ret,'profit_factor':f,'wallet_drawdown_pct':d,'return_to_drawdown':ret/d if d else None,'maximum_positions':n,'maximum_stake_usdt':s},'deduplication':{'v1_raw':len(raw),'v1_removed':len(raw)-len(v1),'v1_retained':len(v1)},'components':comps,'years':years,'gates':gates,'failed_gates':[k for k,v in gates.items() if not v],'artifacts':{k:{'path':v.relative_to(ROOT).as_posix(),'sha256':sha(v)} for k,v in paths.items()}}
        out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(payload,indent=2,sort_keys=True,allow_nan=False)+'\n',encoding='utf-8');print(json.dumps({'status':payload['status'],'decision':payload['decision'],**payload['metrics'],'sha256':sha(out)}));return 0
    except Exception as e: print(f'BLOCKED: {e}',file=sys.stderr);return 2

if __name__=='__main__':raise SystemExit(main())
