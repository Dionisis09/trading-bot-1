import json, pathlib
root = pathlib.Path('user_data/backtest_results')
for p in sorted(root.glob('*.meta.json')):
    try:
        d = json.loads(p.read_text(encoding='utf-8'))
        if 'DualTrendFuturesV5' in d:
            notes = d['DualTrendFuturesV5'].get('notes')
            print(p.name, notes)
    except Exception as e:
        pass
