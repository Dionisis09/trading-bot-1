import zipfile, json, pathlib, datetime, statistics
root = pathlib.Path('user_data/backtest_results')
cutoff = datetime.date.today() - datetime.timedelta(days=365*5)
records = []
for zpath in sorted(root.glob('*.zip')):
    try:
        with zipfile.ZipFile(zpath) as z:
            jname = [n for n in z.namelist() if n.endswith('.json')][0]
            jd = json.loads(z.read(jname).decode('utf-8'))
            strat = jd.get('strategy')
            if not isinstance(strat, dict):
                continue
            # find strategy keys matching V2R or V4R
            for key in strat.keys():
                if 'v2r' in key.lower() or 'v4r' in key.lower():
                    nested = strat.get(key)
                    if not isinstance(nested, dict):
                        continue
                    # determine normalized strategy name
                    sname = 'V2R' if 'v2r' in key.lower() else 'V4R'
                    # extract start
                    start = None
                    if nested.get('backtest_start'):
                        try:
                            start = datetime.datetime.fromisoformat(nested.get('backtest_start')).date()
                        except Exception:
                            pass
                    if not start and nested.get('backtest_start_ts'):
                        try:
                            start = datetime.date.fromtimestamp(int(nested.get('backtest_start_ts')))
                        except Exception:
                            start = None
                    rec = {
                        'zip': zpath.name,
                        'strategy': sname,
                        'key': key,
                        'start': start,
                        'final_balance': nested.get('final_balance'),
                        'profit_total': nested.get('profit_total') or nested.get('profit_total_abs') or nested.get('profit_mean') or nested.get('profit_total') ,
                        'cagr': nested.get('cagr'),
                        'total_trades': nested.get('total_trades'),
                        'sharpe': nested.get('sharpe')
                    }
                    if start and start >= cutoff:
                        records.append(rec)
    except Exception:
        continue

# separate
v2r = [r for r in records if r['strategy']=='V2R']
v4r = [r for r in records if r['strategy']=='V4R']

print('found', len(v2r), 'V2R records and', len(v4r), 'V4R records (start >=', cutoff.isoformat()+')')

def agg(lst):
    if not lst:
        return {}
    nums = lambda k: [x[k] for x in lst if isinstance(x.get(k),(int,float))]
    return {
        'count': len(lst),
        'avg_cagr': statistics.mean(nums('cagr')) if nums('cagr') else None,
        'median_cagr': statistics.median(nums('cagr')) if nums('cagr') else None,
        'avg_profit': statistics.mean(nums('profit_total')) if nums('profit_total') else None,
        'sum_profit': sum(nums('profit_total')) if nums('profit_total') else None,
        'avg_trades': statistics.mean(nums('total_trades')) if nums('total_trades') else None,
        'avg_sharpe': statistics.mean(nums('sharpe')) if nums('sharpe') else None,
    }

v2r_agg = agg(v2r)
v4r_agg = agg(v4r)

print('\n=== Aggregates ===')
print('V2R:', v2r_agg)
print('V4R:', v4r_agg)

# list V4R details
if v4r:
    print('\n=== V4R details ===')
    for r in v4r:
        print(r)

# compare single V4R entries to V2R averages
if v4r and v2r:
    print('\n=== Comparison (per V4R entry vs V2R averages) ===')
    for r in v4r:
        print('\nV4R zip:', r['zip'])
        for metric in ('cagr','profit_total','total_trades','sharpe'):
            v = r.get(metric)
            avg = v2r_agg.get('avg_'+metric) if metric!='total_trades' else v2r_agg.get('avg_trades')
            # handle naming mismatch
            if metric=='profit_total': avg = v2r_agg.get('avg_profit')
            print(f" {metric}: V4R={v} vs V2R_avg={avg}")

# save simple CSV summary
out = pathlib.Path('user_data/backtest_results/compare_v4r_v2r_summary.csv')
with out.open('w',encoding='utf-8') as f:
    f.write('zip,strategy,start,cagr,profit_total,total_trades,sharpe\n')
    for r in sorted(records, key=lambda x: (x['strategy'], str(x['start']) if x['start'] else '')):
        f.write(f"{r['zip']},{r['strategy']},{r['start']},{r.get('cagr')},{r.get('profit_total')},{r.get('total_trades')},{r.get('sharpe')}\n")

print('\nWrote summary to user_data/backtest_results/compare_v4r_v2r_summary.csv')
