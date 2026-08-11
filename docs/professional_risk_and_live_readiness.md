# Professional risk controls and live readiness

## Current safety state

The system runs Binance futures in Freqtrade dry-run mode. Live trading is not
authorized and no automatic path can enable it. Positive backtest output is
historical simulation evidence, not a profit guarantee.

The two Freqtrade services become healthy only after an authenticated `/health`
response contains a valid bot-loop timestamp. The forward monitor waits for
that readiness signal and retries collection failures after 60 seconds instead
of waiting for the normal four-hour cadence.

## Locked account limits

The versioned policy in `user_data/risk_policy.json` rejects new entries when
any account gate fails:

| Gate | Locked limit |
| --- | ---: |
| Daily realized loss | less than 2% of the starting wallet |
| Weekly realized loss | less than 5% |
| Wallet drawdown | no more than 10% |
| Total open stake | no more than 20% |
| Simultaneous open trades | no more than 2 |
| Leverage | 1x maximum |

Missing or invalid policy, wallet, or trade state fails closed. These entry
guards do not force-liquidate existing positions; the strategy stoploss and
normal exit logic remain responsible for open trades.

## Production-profile evidence

The professional backtest profile matches the forward bot's 1,000 USDT wallet,
25 USDT fixed stake, two-position limit, protections, 1x leverage, and explicit
fee. Its source-backed artifacts are:

- `user_data/reports/professional_risk_backtest_summary.csv`
- `user_data/reports/professional_risk_backtest_manifest.json`
- `user_data/reports/execution_stress_report.json`

The deterministic execution test adds fee, slippage, latency, and adverse
funding costs in moderate and severe scenarios. The present qualification is
`FAIL`: the 2022 split misses the moderate profit-factor threshold and becomes
negative under severe costs. A stricter experimental four-of-four confluence
variant also performed worse in 2022 and was rejected; the selected V2R
strategy was retained rather than overfit to one split.

## Readiness states

`user_data/reports/live_readiness.json` combines safety, forward evidence,
account risk, and execution-stress gates:

- `SAFETY_BLOCK`: a configuration or account safety gate failed.
- `EVIDENCE_INCOMPLETE`: safety is intact, but forward or stress evidence is
  not sufficient.
- `READY_FOR_HUMAN_REVIEW`: every automated gate passed; this still does not
  authorize live trading.

Any future live review additionally requires explicit human authorization, a
static VPS IP, a trade-only Binance API key, withdrawals disabled, and an IP
allowlist. The paid VPS account, server address, and SSH access are external
inputs and are not created by this repository.

## Verification

```powershell
docker compose config --quiet
docker compose exec -T forward-monitor python -m unittest discover -s /freqtrade/tools -p 'test_*.py' -v
python tools\validate_execution_stress.py
python tools\build_live_readiness.py
docker compose ps
```

The operational dashboard is available locally at `http://127.0.0.1:8090`.
