# ProfitMax CAGR15 Cycle 5 - Locked Research Plan

Locked after Cycle 4 failed because 2.5x leverage compressed the inherited -10% PnL
stop to roughly a -4% underlying move. No Cycle 5 PnL has been viewed.

## Fixed candidate

- `ProfitMaxCagr15V5`, inheriting Cycle 4 long-only signals and correct margin guard.
- Fixed leverage 2.5x and stoploss -25% of position margin, preserving approximately
  the original -10% underlying-price stop distance.
- Wallet 1,000 USDT, configured margin 300, ATR-sized actual margin <=195 USDT,
  one isolated position, all six Binance futures pairs, 4h, fee 0.075%/side.
- Dedicated fail-closed research policy: daily loss 2%, weekly loss 5%, wallet DD 12%,
  open margin 20%, one trade. It has no live authorization.
- Timerange `20210101-20260801`; no frequency gate or post-result parameter change.

## Gates

- CAGR >=15%, PF >=2.0, Freqtrade wallet DD <=12%, return/DD >=10.
- Each 2021-2025 positive; partial 2026 >-2%; >=80 long trades; zero shorts.
- Every trade leverage exactly 2.5 and peak concurrent margin <=20% wallet.
- Moderate +0.05%/side: CAGR >=13%, PF >=1.70, DD <=15%.
- Severe +0.10%/side: CAGR >=10%, PF >=1.40, DD <=18%.

Passing allows isolated dry-run evaluation only. Live remains unauthorized.
