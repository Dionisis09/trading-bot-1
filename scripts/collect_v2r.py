import json, pathlib, datetime
import zipfile
root = pathlib.Path('user_data/backtest_results')
res = []
for p in sorted(root.glob('*.meta.json')):
    try:
        d = json.loads(p.read_text())
    except Exception:
        continue
    is_v2r = False
    if d.get('strategy') == 'DualTrendFuturesV2R':
        is_v2r = True
    elif isinstance(d.get('strategy'), dict) and d['strategy'].get('name') == 'DualTrendFuturesV2R':
        is_v2r = True
    elif d.get('strat_name') == 'DualTrendFuturesV2R':
        is_v2r = True
    # some meta files use the strategy name as top-level key
    elif any(k == 'DualTrendFuturesV2R' for k in d.keys() if isinstance(k, str)):
        # try to extract nested info
        nested = d.get('DualTrendFuturesV2R')
        if isinstance(nested, dict):
            # inject a normalized view so later code can read timerange/start
            d = {'timerange': nested.get('timerange') or nested.get('timeframe') or nested.get('backtest_start_ts'),
                 'final_balance': nested.get('final_balance'),
                 'profit_abs': nested.get('profit_abs'),
                 'cagr': nested.get('cagr'),
                 'total_trades': nested.get('total_trades'),
                 'win_rate': nested.get('win_rate'),
                 'sharpe': nested.get('sharpe'),
                 'strategy': 'DualTrendFuturesV2R'}
            is_v2r = True
    if not is_v2r:
        continue
    timerange = d.get('timerange') or ''
    start_date = None
    if isinstance(timerange, str) and '-' in timerange:
        a = timerange.split('-')[0]
        for fmt in ('%Y%m%d','%Y-%m-%d','%Y/%m/%d'):
            try:
                start_date = datetime.datetime.strptime(a, fmt).date()
                break
            except Exception:
                pass
    res.append((p.name, start_date, d))

    # try to open matching zip files for richer metrics
    for i, (name, start, data) in enumerate(list(res)):
        zip_path = root / (pathlib.Path(name).stem + '.zip')
        if zip_path.exists():
            try:
                with zipfile.ZipFile(zip_path, 'r') as z:
                    for member in z.namelist():
                        if member.endswith('.json'):
                            try:
                                txt = z.read(member).decode('utf-8')
                                jd = json.loads(txt)
                            except Exception:
                                continue
                            # look for keys
                                # look for keys at top-level
                                for key in ('final_balance','profit_abs','cagr','total_trades','win_rate','sharpe'):
                                    if key in jd and (data.get(key) is None):
                                        data[key] = jd.get(key)
                                # also check nested strategy section
                                strat = jd.get('strategy')
                                if isinstance(strat, dict):
                                    nested = strat.get('DualTrendFuturesV2R') or strat.get('DualTrendFuturesV2R'.lower())
                                    if isinstance(nested, dict):
                                        for key in ('final_balance','profit_abs','cagr','total_trades','win_rate','sharpe'):
                                            if key in nested and (data.get(key) is None):
                                                data[key] = nested.get(key)
                            # if timerange missing, try to parse from fields
                            if not start:
                                tr = jd.get('timerange') or jd.get('timeframe')
                                if isinstance(tr, str) and '-' in tr:
                                    a = tr.split('-')[0]
                                    try:
                                        start = datetime.datetime.strptime(a, '%Y%m%d').date()
                                    except Exception:
                                        pass
                            # save back
                            res[i] = (name, start, data)
                            break
            except Exception:
                pass
today = datetime.date.today()
try:
    cutoff = datetime.date(today.year - 5, today.month, today.day)
except Exception:
    cutoff = datetime.date(today.year - 5, 1, 1)

selected = [(n,s,d) for (n,s,d) in res if s and s >= cutoff]
if not selected:
    selected = res

print(f'Found {len(selected)} V2R meta files (showing latest):')
for name, start, data in selected[-20:]:
    print('-' * 60)
    print(name)
    print('  start:', start)
    print('  timerange:', data.get('timerange'))
    print('  final_balance:', data.get('final_balance'))
    print('  profit_abs:', data.get('profit_abs'))
    print('  cagr:', data.get('cagr'))
    print('  total_trades:', data.get('total_trades'))
    print('  win_rate:', data.get('win_rate'))
    print('  sharpe:', data.get('sharpe'))

# summary aggregate
if selected:
    profits = [d.get('profit_abs', 0) for _,_,d in selected]
    cags = [d.get('cagr') for _,_,d in selected if isinstance(d.get('cagr'), (int,float))]
    trades = [d.get('total_trades') for _,_,d in selected if isinstance(d.get('total_trades'), int)]
    print('\nAggregate (selected files):')
    print('  files:', len(selected))
    print('  sum_profit_abs:', sum([p or 0 for p in profits]))
    if cags:
        print('  avg_cagr:', sum(cags)/len(cags))
    if trades:
        print('  avg_trades:', sum(trades)/len(trades))
