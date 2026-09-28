import zipfile, json, pathlib, datetime
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
            nested = strat.get('DualTrendFuturesV2R')
            if not isinstance(nested, dict):
                continue
            # extract start
            start = None
            if nested.get('backtest_start'):
                try:
                    start = datetime.datetime.fromisoformat(nested.get('backtest_start')).date()
                except Exception:
                    try:
                        start = datetime.date.fromtimestamp(int(nested.get('backtest_start_ts')))
                    except Exception:
                        start = None
            elif nested.get('backtest_start_ts'):
                try:
                    start = datetime.date.fromtimestamp(int(nested.get('backtest_start_ts')))
                except Exception:
                    start = None
            # metrics
            rec = {
                'zip': zpath.name,
                'start': start,
                'final_balance': nested.get('final_balance'),
                'profit_total': nested.get('profit_total') or nested.get('profit_total_abs') or nested.get('profit_mean'),
                'cagr': nested.get('cagr'),
                'total_trades': nested.get('total_trades'),
                'sharpe': nested.get('sharpe')
            }
            if start and start >= cutoff:
                records.append(rec)
    except Exception:
        continue

print('Found', len(records), 'V2R zips with start >=', cutoff.isoformat())
if records:
    import statistics
    cagr = [r['cagr'] for r in records if isinstance(r['cagr'], (int,float))]
    profit = [r['profit_total'] for r in records if isinstance(r['profit_total'], (int,float))]
    trades = [r['total_trades'] for r in records if isinstance(r['total_trades'], int)]
    sharpe = [r['sharpe'] for r in records if isinstance(r['sharpe'], (int,float))]
    print('avg_cagr:', statistics.mean(cagr) if cagr else None)
    print('sum_profit:', sum(profit) if profit else None)
    print('avg_trades:', statistics.mean(trades) if trades else None)
    print('avg_sharpe:', statistics.mean(sharpe) if sharpe else None)
    print('\nSample entries:')
    for r in records[-10:]:
        print(r)
else:
    print('No recent records found.')
