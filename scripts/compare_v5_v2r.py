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
            for key in strat.keys():
                kl = key.lower()
                if 'v2r' in kl or 'v5' in kl:
                    nested = strat.get(key)
                    if not isinstance(nested, dict):
                        continue
                    sname = 'V2R' if 'v2r' in kl else 'V5'
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

v2r = [r for r in records if r['strategy']=='V2R']
v5 = [r for r in records if r['strategy']=='V5']

print('found', len(v2r), 'V2R records and', len(v5), 'V5 records (start >=', cutoff.isoformat()+')')

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
v5_agg = agg(v5)

print('\n=== Aggregates ===')
print('V2R:', v2r_agg)
print('V5:', v5_agg)

out = pathlib.Path('user_data/backtest_results/compare_v5_v2r_summary.csv')
with out.open('w',encoding='utf-8') as f:
    f.write('zip,strategy,start,cagr,profit_total,total_trades,sharpe\n')
    for r in sorted(records, key=lambda x: (x['strategy'], str(x['start']) if x['start'] else '')):
        f.write(f"{r['zip']},{r['strategy']},{r['start']},{r.get('cagr')},{r.get('profit_total')},{r.get('total_trades')},{r.get('sharpe')}\n")

print('\nWrote summary to', out)
