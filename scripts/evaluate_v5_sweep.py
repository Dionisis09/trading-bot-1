import json, zipfile, pathlib
root = pathlib.Path('user_data/backtest_results')
# find baseline V2R validation
baseline = None
for p in root.glob('*.meta.json'):
    try:
        d = json.loads(p.read_text(encoding='utf-8'))
        for k,v in d.items():
            notes = v.get('notes','')
            if notes.startswith('phase=dual_v2r;') and 'split=validation' in notes:
                base = p.stem
                with zipfile.ZipFile(root / f"{base}.zip") as z:
                    jd = json.loads(z.read_text(f"{base}.json", encoding='utf-8'))
                stats = jd['strategy'].get(k)
                baseline = {'artifact': base+'.zip','strategy':k,'return_pct':100*float(stats.get('profit_total',0)),'pf':float(stats.get('profit_factor',0)),'dd_pct':100*float(stats.get('max_drawdown_account',0))}
                break
    except Exception:
        pass

print('Baseline V2R validation:', baseline)

rows=[]
for p in root.glob('*.meta.json'):
    try:
        d = json.loads(p.read_text(encoding='utf-8'))
        for k,v in d.items():
            notes = v.get('notes','')
            if notes.startswith('phase=dual_v5_sweep;') and 'split=validation' in notes:
                base = p.stem
                with zipfile.ZipFile(root / f"{base}.zip") as z:
                    jd = json.loads(z.read_text(f"{base}.json", encoding='utf-8'))
                stats = jd['strategy'].get(k)
                rows.append({'variant': v.get('notes').split(';')[1].split('=',1)[1], 'artifact':base+'.zip', 'return_pct':100*float(stats.get('profit_total',0)),'pf':float(stats.get('profit_factor',0)),'dd_pct':100*float(stats.get('max_drawdown_account',0))})
    except Exception:
        pass

print('\nVariants validation results:')
for r in sorted(rows, key=lambda x: -x['return_pct']):
    print(r)

# write CSV
out = root.parent / 'reports' / 'v5_sweep_validation_summary.csv'
out.parent.mkdir(parents=True, exist_ok=True)
with out.open('w',encoding='utf-8') as f:
    f.write('variant,artifact,return_pct,pf,dd_pct\n')
    for r in rows:
        f.write(f"{r['variant']},{r['artifact']},{r['return_pct']},{r['pf']},{r['dd_pct']}\n")
print('\nWrote', out)
