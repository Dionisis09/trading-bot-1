# ProfitMax20 V3 - locked retrospective research plan

V2 was technically blocked because the 6 USDT activity stake produced no
orders and the 20% internal circuit breaker truncated the calendar run. V3 is
a separate, immutable cycle. It does not alter V1, V2, or any active bot.

The primary interval is `[2021-08-01, 2026-08-01)`; the secondary interval is
`[2021-01-01, 2026-01-01)`. The aggregate wallet is 1,000 USDT. Both sleeves
use Binance isolated USDT futures, a 0.075% fee on each side, recorded funding,
and next-candle Freqtrade execution.

The qualified long-only swing signal uses 3.78x, one position, at most 20%
margin, and a `-0.378` leveraged stop, retaining an approximate 10% underlying
price stop. Its internal research circuit breaker is 25% so a path-dependent
early stop cannot hide later historical trades. Qualification remains stricter:
the measured portfolio drawdown must not exceed 20%.

The activity sleeve selects the top two seven-day momentum ranks from the
audited 50-pair universe, behind the 30-day BTC trend gate, at 08:00 and 20:00
UTC. It holds eight hours, uses 1x, 10 USDT per position, and two positions.

The rolling-five-year gates are at least 1.00 trade/day; baseline and severe
(extra 0.10% per entry and exit) CAGR at least 20%; baseline and severe profit
factor at least 1.50; realized drawdown at most 20%; concurrent margin at most
25% and notional at most 75%; no calendar segment below -2% of wallet and at
least four positive calendar segments; exact reconciliation and sanitized ZIPs.

All history was previously observed. Passing is retrospective evidence only.
It can authorize a separate credential-free isolated dry-run, never live
trading or automatic promotion.
