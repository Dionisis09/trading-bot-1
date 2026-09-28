import json, pathlib
root = pathlib.Path('user_data/backtest_results')
for p in sorted(root.glob('*.meta.json')):
    try:
        data = json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        continue
    for k,v in data.items():
        if isinstance(v, dict) and 'notes' in v:
            notes = v.get('notes')
            if isinstance(notes, str) and 'split=' in notes:
                print(p.name, k, v.get('timerange'), notes)
