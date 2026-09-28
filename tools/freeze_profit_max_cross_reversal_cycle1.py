#!/usr/bin/env python3
import hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];REPORT=ROOT/'user_data/reports/profit_max_cross_reversal_cycle1'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
 files=[ROOT/'docs/profit_max_cross_sectional_reversal_cycle1_locked_plan.md',ROOT/'user_data/strategies/ProfitMaxCrossSectionalReversal.py',ROOT/'user_data/strategies/ProfitMaxCrossSectional.py',ROOT/'user_data/strategies/DualTrendFuturesRisk.py',ROOT/'user_data/strategies/ProfessionalRisk.py',ROOT/'user_data/config-profit-max-liquid50-cycle1.json',ROOT/'user_data/config-profit-max-cross-reversal-cycle1-overlay.json',ROOT/'user_data/risk_policy.json',ROOT/'tools/test_profit_max_cross_sectional_reversal.py',Path(__file__).resolve(),ROOT/'user_data/reports/profit_max_cross_sectional_short_horizon_cycle1/research_freeze_manifest.json']
 if any(not p.is_file() or p.is_symlink() for p in files):print('BLOCKED',file=sys.stderr);return 2
 out=REPORT/'train.zip'
 if out.exists():print('BLOCKED: output exists',file=sys.stderr);return 3
 payload={'schema_version':'1.0','cycle':'profit_max_cross_reversal_cycle1','status':'FROZEN_BEFORE_PNL','validation_revealed':False,'live_trading_authorized':False,'timerange':'20210101-20240101','fee_per_side':.00075,'files':[{'path':p.relative_to(ROOT).as_posix(),'sha256':sha(p),'bytes':p.stat().st_size} for p in files],'artifacts':{'train':out.relative_to(ROOT).as_posix()}}
 REPORT.mkdir(parents=True,exist_ok=True);m=REPORT/'research_freeze_manifest.json';m.write_text(json.dumps(payload,indent=2,sort_keys=True)+'\n');print(json.dumps({'status':payload['status'],'sha256':sha(m)}));return 0
if __name__=='__main__':raise SystemExit(main())
