# ProDayTraderV4 Cycle 3 - Locked Lookahead Pricing Retry

- Status: `LOCKED_BEFORE_FIRST_V4_CYCLE3_PNL_RUN` on 2026-08-16.
- No strategy, config, data, gate, threshold, or performance change is allowed.
- Recursive PASS remains the V4 Cycle 1 result.
- Cycle 2 lookahead stopped before a probe because disabling order-book pricing
  requires Binance futures ticker pricing, which the pinned exchange contract marks
  unavailable. Source inspection establishes the compatible technical override:
  market `price_side="other"` with `use_order_book=true` for entry and exit.
- The override exists only inside the official bias tool. The frozen trading config
  remains byte-identical. Private API calls, PnL parsing, deployment, and live trading
  remain forbidden.
- Lookahead contract remains three pairs, `20240101-20260101`, minimum 100, target
  120, zero biased entry/exit/indicator fields, all T1/R1 sides and pairs represented.
- Strategy SHA256 `ecca8f37bf162bd6f1e9d8d0bb6ccc06910e3c65ab95c9b4a06ba8cd99c1fcea`.
- Config SHA256 `307fa8d43b0356b28a7b0e451c57cc59ad35b969bb1a0351e3d23c8f9d666c26`.
- Recursive PASS SHA256 `436c6b45bf31ac0b955cda8b173be6d7c2ab1b14a97fa83f69bc4794c0f43850`.
- Cycle 2 plan SHA256 `a67927998aa57c5638b7cb0aa0ea810b9ccf680fa79d2248dd35f38eaf870cbd`.
- Cycle 2 manifest SHA256 `99fc2f93b295e07f20f1833beab8db595a34a6d33455c9a0fefc495b0d42a37f`.
- Cycle 2 lookahead FAIL SHA256 `875f8215da5dedda3bc365637aeed26fd108c5d09e23da44e08744f557a58617`.
- Cycle 2 runner SHA256 `f20db019f93c1383f7284e8a2aeea9cf8ff66b33a75cc0e6219bddafdf20892f`.
- Passing unlocks only TRAIN; final approval can only be `APPROVE_SEPARATE_DRY_RUN`.
