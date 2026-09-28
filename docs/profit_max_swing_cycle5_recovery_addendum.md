# Profit-Max Swing Cycle 5 - frozen recovery addendum

Status: `LOCKED_BEFORE_PNL_PARSE`. This addendum handles an operational sanitizer return only. It does not permit a TRAIN rerun, parameter change, threshold change or candidate change.

The original runner completed exactly one TRAIN backtest and stopped before parsing PnL because its embedded sanitizer subprocess returned non-zero. Recovery must use only the explicit existing receipt and ZIP:

- receipt `.last_result.json`, SHA256 `4c4f5e1db653805fb6b611539c4d0d68c2a294a4f6405d2636191cf32c553a1c`
- metadata `backtest-result-2026-08-16_12-03-41.meta.json`, SHA256 `478a373912344d66553eb52f3af1a89392d01dcfeda4e0b6b945e3b53a888aae`
- post-failed-sanitizer ZIP `backtest-result-2026-08-16_12-03-41.zip`, SHA256 `724302fcbe695f6dda046f429b03ff5f29f62541212b7c07a8fc41d40bfd104b`

Recovery first runs the established sanitizer directly and requires exit 0, ZIP integrity and exact five-candidate inventory. Only then may TRAIN PnL be parsed. The original locked gates decide whether VALIDATION can run. Subsequent splits use the original frozen image, config, candidates, dates and costs. Any failure stops the cycle; no TRAIN replay is allowed.
