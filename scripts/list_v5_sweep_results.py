import json, pathlib
root = pathlib.Path('user_data/backtest_results')
rows = []
for p in sorted(root.glob('*.meta.json')):
    try:
        d = json.loads(p.read_text(encoding='utf-8'))
        for k,v in d.items():
            notes = v.get('notes','')
            if notes.startswith('phase=dual_v5_sweep'):
                # parse variant and split
                parts = {part.split('=',1)[0]:part.split('=',1)[1] for part in notes.split(';') if '=' in part}
                rows.append((p.name, parts.get('variant'), parts.get('split'), parts.get('fee')))
    except Exception:
        pass
for r in rows:
    print(*r)
print('\nTotal entries:', len(rows))
