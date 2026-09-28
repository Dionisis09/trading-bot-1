import zipfile, json, sys, pprint
p = sys.argv[1] if len(sys.argv) > 1 else 'user_data/backtest_results/backtest-result-2026-08-11_09-45-14.zip'
with zipfile.ZipFile(p) as z:
    names = z.namelist()
    print('members:', names)
    jsons = [n for n in names if n.endswith('.json')]
    if not jsons:
        print('no json inside')
    for name in jsons:
        print('\n---', name)
        data = json.loads(z.read(name).decode('utf-8'))
        pprint.pprint({k: type(v).__name__ for k,v in data.items()})
        # if strategy dict, show keys under it
        strat = data.get('strategy')
        if isinstance(strat, dict):
            print('strategy keys:', list(strat.keys())[:10])
            if 'DualTrendFuturesV2R' in strat:
                print('DualTrendFuturesV2R sample keys:', list(strat['DualTrendFuturesV2R'].keys())[:40])
                # print some values
                for key in ('final_balance','profit_abs','cagr','total_trades','win_rate','sharpe'):
                    print(key, strat['DualTrendFuturesV2R'].get(key))
