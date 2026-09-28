# ProDayTraderV4 Cycle 2 - Locked Lookahead Compatibility Retry

- Status: `LOCKED_BEFORE_FIRST_V4_CYCLE2_PNL_RUN` on 2026-08-16.
- Strategy, trading config, risk rules, data, recursive result, performance gates,
  splits, and cost stresses are unchanged from V4 Cycle 1.
- Cycle 1 recursive analysis passed. Its lookahead runner then stopped before a
  probe because Freqtrade forces market orders but requires market-compatible
  `entry_pricing.price_side="other"`; the frozen trading config correctly uses
  `same` for its normal order-book policy.
- Cycle 2 changes only the transient bias-tool config after the official lookahead
  overrides: entry/exit price side becomes `other` and order-book pricing is disabled.
  This cannot change the bot config and cannot authorize trading.
- Lookahead remains all-pair `20240101-20260101`, minimum 100, target 120, requiring
  zero biased entries/exits/indicators and representation of T1/R1 long/short and
  BTC/ETH/BNB. Only a pass unlocks TRAIN; no PnL is parsed by this gate.
- Runtime digest:
  `sha256:da3428fde0f7f9f976eaafba8abc7eba42bf978f23e4808347e15d476ad9a643`.
- Strategy SHA256:
  `ecca8f37bf162bd6f1e9d8d0bb6ccc06910e3c65ab95c9b4a06ba8cd99c1fcea`.
- Trading config SHA256:
  `307fa8d43b0356b28a7b0e451c57cc59ad35b969bb1a0351e3d23c8f9d666c26`.
- V4 Cycle 1 plan SHA256:
  `8428e1380f3ca439f252fb119211105fdcaa0a559e6c07e6f49a540641352745`.
- V4 Cycle 1 manifest SHA256:
  `bf30614be68d1889aa8d886e3c8c832c555aca19af9f80d41a4915b72ad141c8`.
- Recursive PASS SHA256:
  `436c6b45bf31ac0b955cda8b173be6d7c2ab1b14a97fa83f69bc4794c0f43850`.
- Cycle 1 lookahead FAIL SHA256:
  `3859eed0f56dec648eab15934d73fe7964ecc9a0ae2ad4a8757e9a6a7a131c62`.
- Frozen failed runner SHA256:
  `66b5ed1df09069acc93b5a414c716517ac784b4373b73b160a42df25def448a6`.
- A full pass can at most `APPROVE_SEPARATE_DRY_RUN`; live remains forbidden.
