from pathlib import Path

BASE = Path(__file__).resolve().parents[1] / 'user_data' / 'strategies' / 'DualTrendFuturesV5.py'
TEMPL_DIR = Path(__file__).resolve().parents[1] / 'user_data' / 'strategies'

param_grid = [
    {'risk_exposure_fraction':0.68, 'target_atr_pct':0.024, 'minimum_volatility_scalar':0.4, 'maximum_volatility_scalar':1.05},
    {'risk_exposure_fraction':0.72, 'target_atr_pct':0.028, 'minimum_volatility_scalar':0.45, 'maximum_volatility_scalar':1.10},
    {'risk_exposure_fraction':0.76, 'target_atr_pct':0.032, 'minimum_volatility_scalar':0.5, 'maximum_volatility_scalar':1.15},
    {'risk_exposure_fraction':0.60, 'target_atr_pct':0.020, 'minimum_volatility_scalar':0.35, 'maximum_volatility_scalar':1.00},
    {'risk_exposure_fraction':0.80, 'target_atr_pct':0.035, 'minimum_volatility_scalar':0.55, 'maximum_volatility_scalar':1.20},
    {'risk_exposure_fraction':0.70, 'target_atr_pct':0.026, 'minimum_volatility_scalar':0.45, 'maximum_volatility_scalar':1.08},
]

src = BASE.read_text(encoding='utf-8')
for idx, p in enumerate(param_grid, start=1):
    name = f'DualTrendFuturesV5_v{idx}'
    content = src
    # replace class name and parameters
    content = content.replace('class DualTrendFuturesV5(', f'class {name}(')
    content = content.replace('risk_exposure_fraction = 0.72', f"risk_exposure_fraction = {p['risk_exposure_fraction']}")
    content = content.replace('target_atr_pct = 0.028', f"target_atr_pct = {p['target_atr_pct']}")
    content = content.replace('minimum_volatility_scalar = 0.45', f"minimum_volatility_scalar = {p['minimum_volatility_scalar']}")
    content = content.replace('maximum_volatility_scalar = 1.10', f"maximum_volatility_scalar = {p['maximum_volatility_scalar']}")
    out = TEMPL_DIR / f'{name}.py'
    out.write_text(content, encoding='utf-8')
    print('wrote', out)
