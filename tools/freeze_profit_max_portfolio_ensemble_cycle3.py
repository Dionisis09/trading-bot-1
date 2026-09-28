#!/usr/bin/env python3
import hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];REPORT=ROOT/'user_data/reports/profit_max_portfolio_ensemble_cycle3'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
 files=[ROOT/'docs/profit_max_portfolio_ensemble_cycle3_locked_plan.md',ROOT/'tools/evaluate_profit_max_portfolio_cycle3_validation.py',Path(__file__).resolve(),ROOT/'user_data/config-profit-max-liquid50-cycle1.json',ROOT/'user_data/config-profit-max-cross-sectional-short-horizon-cycle1-overlay.json',ROOT/'user_data/config-profit-max-swing-cycle5.json',ROOT/'user_data/config-profit-max-portfolio-v5-train-overlay.json',ROOT/'user_data/config-profit-max-portfolio-v1-train-overlay.json',ROOT/'user_data/risk_policy.json',ROOT/'user_data/strategies/ProfitMaxCrossSectional.py',ROOT/'user_data/strategies/ProfitMaxCrossSectionalShortHorizon.py',ROOT/'user_data/strategies/ProfitMaxSwingV5.py',ROOT/'user_data/strategies/DualTrendFuturesV1.py',ROOT/'user_data/strategies/DualTrendFuturesV2.py',ROOT/'user_data/strategies/DualTrendFuturesRisk.py',ROOT/'user_data/strategies/ProfessionalRisk.py',ROOT/'user_data/reports/profit_max_cross_sectional_short_horizon_cycle1/research_freeze_manifest.json',ROOT/'user_data/reports/profit_max_portfolio_ensemble_cycle1/research_freeze_manifest.json']
 if any(not p.is_file() or p.is_symlink() for p in files):print('FREEZE_BLOCKED',file=sys.stderr);return 2
 artifacts={n:(REPORT/(n+'_validation.zip')).relative_to(ROOT).as_posix() for n in ('cross','v5','v1')};artifacts['decision']=(REPORT/'validation_decision.json').relative_to(ROOT).as_posix()
 if any((ROOT/p).exists() for p in artifacts.values()):print('FREEZE_BLOCKED: output exists',file=sys.stderr);return 3
 payload={'schema_version':'1.0','cycle':'profit_max_portfolio_ensemble_cycle3','status':'FROZEN_BEFORE_VALIDATION_PNL','validation_revealed':False,'live_trading_authorized':False,'runtime':'freqtradeorg/freqtrade:2026.7@sha256:da3428fde0f7f9f976eaafba8abc7eba42bf978f23e4808347e15d476ad9a643','timerange':'20240101-20260101','fee_per_side':0.00075,'files':[{'path':p.relative_to(ROOT).as_posix(),'sha256':sha(p),'bytes':p.stat().st_size} for p in files],'artifacts':artifacts}
 REPORT.mkdir(parents=True,exist_ok=True);target=REPORT/'research_freeze_manifest.json';target.write_text(json.dumps(payload,indent=2,sort_keys=True)+'\n',encoding='utf-8');print(json.dumps({'status':payload['status'],'sha256':sha(target)}));return 0
if __name__=='__main__':raise SystemExit(main())
