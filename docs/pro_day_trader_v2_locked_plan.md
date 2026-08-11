# ProDayTraderV2 — Locked Profitability-First Research Plan

## 1. Status, objective, and evidence boundary

- Status: `LOCKED_BEFORE_FIRST_V2_PNL_RUN`.
- Lock date: `2026-08-11` (`Europe/Athens`).
- Cycle identifier: `pro_day_v2_cycle1`.
- The single candidate is `ProDayTraderV2`: deterministic trend/mean-reversion
  candidate entries plus a cost-aware FreqAI LightGBM veto. The model may reject
  a deterministic candidate, but it may never create or reverse an entry, increase
  stake or leverage, relax a stop, or bypass a risk protection.
- Primary objective: maximize robust net return after realistic trading costs,
  subject to hard drawdown, breadth, stability, and causal-data constraints.
- No profitability is assumed or guaranteed. All available historical data has
  already been seen during earlier strategy research, so this cycle can provide
  historical robustness evidence only. It is not a sealed holdout or forward proof.
- No hyperopt, grid search, parameter sweep, post-result threshold edit, pair
  deletion, side deletion, setup deletion, label edit, feature edit, or second
  candidate is allowed in this cycle.
- `DualTrendFuturesV1`, `DualTrendFuturesV2R`, their databases, ports, Compose
  services, monitoring continuity, and live-readiness state remain untouched.
- This plan can authorize at most a third, isolated dry-run after every gate passes.
  It cannot authorize live trading, API keys, leverage above 1x, or automatic
  promotion.

## 2. Frozen files, runtime, and namespaces

- Plan: `docs/pro_day_trader_v2_locked_plan.md`.
- Strategy: `user_data/strategies/ProDayTraderV2.py`.
- Research config: `user_data/config-pro-day-v2-research.json`.
- Existing risk policy: `user_data/risk_policy.json` (unchanged).
- Canonical derived data: `user_data/data/binance/pro_day_v2_canonical/`.
- Reports: `user_data/reports/pro_day_v2_cycle1/`.
- Freeze manifest:
  `user_data/reports/pro_day_v2_cycle1/research_freeze_manifest.json`.
- Trial ledger: `user_data/reports/pro_day_v2_cycle1/trial_ledger.json`.
- FreqAI identifier: `proday-v2-cycle1-canonical5m-lgbm-20260811`.
- Research-only runtime, linux/amd64:
  `freqtradeorg/freqtrade:2026.7_freqai@sha256:2a3ed85c4b27700de3a48feb7e7544a56ca2fa7addebc424f08cea5ddcefd000`.
- The existing standard Freqtrade image remains the runtime for V1/V2R. A missing,
  incompatible, or digest-mismatched FreqAI image is `TECHNICAL_BLOCKED`; installing
  packages into the standard image or silently falling back to another model is
  forbidden.

## 3. Market, execution convention, and time splits

- Exchange/mode: Binance USD-M USDT perpetual futures, isolated margin, 1x.
- Fixed universe:
  - `BTC/USDT:USDT`
  - `ETH/USDT:USDT`
  - `BNB/USDT:USDT`
- Base timeframe: 5m. Informative timeframes: 15m, 1h, and 4h.
- UTC only, closed candles only. A decision on base candle `t` is executable no
  earlier than `open[t+1]`. An informative candle becomes available only after its
  real close through Freqtrade's causal informative merge.
- Initial model-history period: `[2021-01-01, 2022-01-01)`; no qualification PnL.
- TRAIN OOS: `[2022-01-01, 2024-01-01)`.
- VALIDATION OOS: `[2024-01-01, 2026-01-01)`; revealed once after TRAIN passes.
- CURRENT_PARTIAL OOS: `[2026-01-01, 2026-08-01)`; revealed only after TRAIN and
  VALIDATION pass.
- Canonical continuous qualification replay: `[2022-01-01, 2026-08-01)`.
- FreqAI walk-forward: previous 365 calendar days train each model; 30 calendar days
  predict; then advance by 30 days without changing strategy, features, target,
  model parameters, or gates. Earlier OOS observations may enter later rolling
  training windows as they would in production, but no result may change this plan.

## 4. Canonical 5m data gate before any PnL

The only OHLCV source of truth is the three original Binance futures 5m files:

- `user_data/data/binance/futures/BTC_USDT_USDT-5m-futures.feather`
- `user_data/data/binance/futures/ETH_USDT_USDT-5m-futures.feather`
- `user_data/data/binance/futures/BNB_USDT_USDT-5m-futures.feather`

For each pair, the pipeline must copy the exact 5m series and derive 15m, 1h, and
4h candles from complete, UTC-aligned 5m bins using `open=first`, `high=max`,
`low=min`, `close=last`, and `volume=sum`. Native Binance 15m/1h/4h OHLCV files
are forbidden in the V2 canonical directory and are not a reconciliation target.
This is a new source policy, not a relaxation of the rejected V1 native-timeframe
policy.

Before PnL, the immutable data report and manifest must prove:

- source coverage exactly `2020-12-01T00:00:00Z` through
  `2026-08-01T23:55:00Z` for each pair;
- exactly 596,160 source 5m rows per pair;
- zero duplicate timestamps, missing expected timestamps, null/non-finite OHLCV,
  invalid OHLC relationships, non-positive lows, or negative volume;
- no partial aggregate bins;
- per pair, exactly 198,720 15m rows, 49,680 1h rows, and 12,420 4h rows across
  the full source range;
- exact round-trip reconstruction of every aggregate from its constituent 5m rows;
- SHA256 for every source and derived file, generator source, audit source, and
  report; and a lineage record mapping each derived hash to its source 5m hash.

Any failure yields `DATA_BLOCKED`; no backtest, model fitting, or PnL parsing is
permitted. Missing external data is never imputed as zero. The existing limited
order-flow, open-interest, and taker data remain shadow-only and are excluded from
all V2 entries, labels, and ML features. Historical funding is included in the
backtest cost accounting, not as an entry feature.

## 5. Deterministic candidate entries

The two fixed setups are computed from completed candles. They have separate tags,
sides, regimes, rejection masks, and result attribution. A row cannot create both
a long and a short. Trend has priority only if a numerical edge-case overlap occurs.

### T1 — trend continuation

Long candidate:

1. 4h `EMA50 > EMA200` and `EMA50 > EMA50.shift(3)`;
2. 1h `log(close / close.shift(24)) > 0` and `ADX14 >= 18`;
3. 15m `EMA20 > EMA50`;
4. base 5m close crosses above EMA20 after being at or below EMA20 on the prior bar;
5. base volume is greater than the median of the previous 20 completed 5m bars.

Short is exactly symmetric, using `<`, negative momentum, and a cross below EMA20.

### R1 — flat-regime mean reversion

- Flat gate: 1h `ADX14 < 20`, and neither 4h T1 trend direction is active.
- Rolling 48-bar VWAP uses completed 5m OHLCV. `z48` is the distance from VWAP
  divided by the rolling 48-bar standard deviation of close.
- Long candidate: prior `z48 < -2.0`, current `z48 >= -2.0`, current close above
  current open, and volume greater than the median of the previous 20 completed bars.
- Short is symmetric around `+2.0` with a bearish current candle.
- R1 exits at the first completed-bar cross of `z48=0` or after 12 base candles.

## 6. Frozen ML veto

- Model: FreqAI `LightGBMRegressor`, one model per pair under the fixed identifier.
- The ML model is trained only on deterministic candidate rows. Non-candidate labels
  are unavailable and must be excluded by the training pipeline, never converted to
  zero.
- Horizon `H=12` base candles. For candidate side `s` (`+1` long, `-1` short):

  `target[t] = s * log(open[t+13] / open[t+1]) - 0.0026`

  The 26 bps hurdle equals moderate locked round-trip friction: baseline 5 bps fee
  per side, an additional 2 bps fee per side, 5 bps slippage per side, and 2 bps
  one-way latency. Funding remains in the backtest/stress ledger.
- Entry is allowed only when the deterministic candidate exists,
  `do_predict == 1`, the prediction is finite, and predicted target `> 0`.
  Missing, stale, outlier, schema-mismatched, or failed prediction vetoes the trade.
- The model cannot alter side, setup, stake, leverage, stop, or exit.

Exact numeric feature schema, with no automatic feature expansion:

1. 5m log returns over 1, 3, and 12 bars;
2. `(EMA20_15m - EMA50_15m) / ATR14_15m`;
3. 1h 24-bar log momentum and `ADX14_1h`;
4. `(EMA50_4h - EMA200_4h) / ATR14_4h`;
5. position inside the previous, shifted 20-candle 15m channel;
6. 5m `z48`, `ATR14/close`, 24h realized volatility, and log volume relative to
   the previous 20-bar median;
7. BTC 1h 24-bar momentum, BTC 4h normalized trend gap, and BTC 24h realized
   volatility;
8. pair 1h 24-bar momentum minus BTC 1h 24-bar momentum;
9. fixed numeric flags `setup_T1`, `setup_R1`, and candidate `side`.

Forbidden ML inputs include raw price level, wallet/PnL, future/current incomplete
candles, trade outcome, current position state, order flow, OI, taker ratio, news,
LLM output, automatic correlated-pair expansion, automatic shifted-candle expansion,
or any feature selected after PnL.

FreqAI parameters:

- `train_period_days=365`, `backtest_period_days=30`,
  `expiration_hours=12`, `purge_old_models=2`;
- `include_timeframes=["5m","15m","1h","4h"]`,
  `include_corr_pairlist=["BTC/USDT:USDT"]`,
  `include_shifted_candles=0`, `indicator_periods_candles=[14]`;
- `buffer_train_data_candles=13`, PCA/SVM/DBSCAN/noise disabled;
- chronological data only: `shuffle=false`, `shuffle_after_split=false`,
  `reverse_train_test_order=false`, `test_size=0`;
- LightGBM: `n_estimators=200`, `learning_rate=0.03`, `num_leaves=15`,
  `max_depth=4`, `min_child_samples=200`, `subsample=1.0`,
  `colsample_bytree=1.0`, `reg_alpha=0.0`, `reg_lambda=1.0`, `n_jobs=2`,
  `deterministic=true`, `force_col_wise=true`, and all random/data/feature/bagging
  seeds fixed to `20260811`.

## 7. Position risk and exits

- `position_adjustment_enable=False`; no DCA, martingale, averaging down, or pyramiding.
- Leverage callback always returns 1.0; isolated margin only.
- Hard emergency stop: -4%.
- Risk budget: 0.25% of wallet per trade.
- Sizing stop distance: `clamp(1.5 * ATR14_5m / close, 0.75%, 3.0%)`.
- Stake is the minimum of proposed stake, exchange maximum, 10% of wallet, and
  `0.25% wallet / sizing_stop_distance`. Invalid input or an exchange minimum above
  safe stake yields zero stake.
- T1 signal exit: completed 15m EMA20/EMA50 cross against the position.
- R1 signal/time exit: z48 crosses zero or position age reaches 60 minutes.
- Any losing position exits at 180 minutes; every position exits at 720 minutes.
- Profit protection: at +0.8% protect approximately break-even; at +1.5% cap
  distance from current rate at 0.6%; at +2.5% cap it at 0.8%.
- Protections are always enabled: cooldown 3 candles; StoplossGuard
  lookback/trade-limit/stop `144/3/48`; MaxDrawdown
  lookback/trade-limit/stop/max-DD `2016/10/288/8%`.

## 8. Pre-PnL technical and leakage gates

Before qualification PnL:

- validate the exact FreqAI image digest, Python/Freqtrade/LightGBM imports, and
  availability of `LightGBMRegressor`;
- validate config schema, futures/isolated/1x, dry-run, fee, fixed universe,
  exact data directory, identifier, target, features, model parameters, and splits;
- strategy discovery must report `ProDayTraderV2` status OK;
- unit tests must prove higher-timeframe availability, shifted channel extrema,
  candidate symmetry, target indices `t+1` and `t+13`, non-candidate NaN labels,
  the 26 bps deduction, prediction fail-closed behavior, 1x leverage, safe sizing,
  and deterministic tags;
- a feature audit must prove that changing any row after `t` cannot alter a feature,
  candidate, or prediction input at or before `t`;
- the 13-candle end buffer must be present in every model training fold and every
  fold must record train start/stop, prediction start/stop, row counts, feature-list
  hash, source-data hash, model parameters, model hash, and image digest;
- run Freqtrade lookahead analysis for every activated deterministic side/setup.
  A non-triggered side/setup is not considered tested. Run recursive analysis with
  fixed startup counts `[199,399,799,1599,3199,6399,12799]`; select the smallest
  pre-PnL count with zero signal differences and at most 0.01% variance in every
  decision-critical indicator. Unsupported or inconclusive analysis fails closed.

Any technical, data, source, image, model, feature, label, bias, or recursion failure
is `REJECT_PRO_DAY_TRADER_V2`; no later performance can override it.

## 9. Sequential qualification and performance gates

The manifest hashes the locked plan, strategy, config, risk policy, generator,
auditor, exact image digest, source 5m files, derived files, and explicit artifact
filenames before the first PnL run. Artifacts are selected by exact path, never by
mtime or `latest`.

1. Run TRAIN once. A fail ends qualification as `KEEP_OFFLINE_RESEARCH`.
2. Only TRAIN pass unlocks one VALIDATION run. A fail ends qualification.
3. Only TRAIN+VALIDATION pass unlocks CURRENT_PARTIAL and diagnostics.
4. No result may cause a code/config/plan/data/model change in this cycle.

TRAIN OOS gates:

- at least 120 trades, return > 0, profit factor >= 1.25;
- Freqtrade wallet-curve max drawdown <= 12%; return/drawdown >= 1.00.

VALIDATION OOS gates:

- at least 120 trades, return > 0, profit factor >= 1.35;
- wallet-curve max drawdown <= 10%; return/drawdown >= 1.20;
- each of 2024 and 2025: at least 40 trades, return > 0, PF >= 1.15,
  DD <= 10%;
- each pair: at least 25 trades, PF >= 0.90, return > -2%; at least two of three
  pairs net positive; largest positive-pair contribution <= 60%;
- long and short separately: at least 35 trades, net > 0, PF >= 1.05;
- T1 and R1 separately: at least 25 trades; any setup with at least 20 trades must
  have net >= 0 and PF >= 1.00;
- largest winning-trade contribution <= 20% of gross positive PnL.

CURRENT_PARTIAL gates:

- at least 20 trades, return >= 0, PF >= 1.10, DD <= 8%.

Stability gates on the continuous OOS stream:

- at least three of the four full years 2022-2025 positive;
- median full-year PF >= 1.20; worst full-year return > -3%;
- at least 10 of 16 full quarters positive and at least 5 of 8 validation quarters
  positive; worst full-quarter return > -3%;
- report pair x side x setup x year x quarter and BTC-4h bull/bear/sideways regime.
  Each regime with at least 20 validation trades must have net >= 0 and PF >= 1.00;
  every regime, regardless of count, must return > -1%.

## 10. Execution-cost stress and reconciliation

Baseline: 5 bps fee per side plus recorded funding.

- Moderate: +2 fee bps/side, +5 slippage bps/side, +2 one-way latency bps,
  funding x1.5.
- Severe: +10 fee bps/side, +15 slippage bps/side, +5 one-way latency bps,
  funding x3.

VALIDATION moderate: return > 0, PF >= 1.20, DD <= 12%, return/DD >= 0.80.
VALIDATION severe: return > 0, PF >= 1.05, DD <= 15%, return/DD >= 0.50.
For each validation year, moderate net > 0 and PF >= 1.10; severe return > -2%
and PF >= 0.95. Stress uses identical raw trades and ordering with no
outcome-dependent repricing.

Every ZIP is sanitized before hashing and must pass integrity/redaction checks.
Embedded strategy/config hashes must equal the frozen workspace files. Independent
reconciliation must match exact trade/win/loss/draw/long/short/pair/setup counts,
profit within `1e-6`, PF within `1e-12`, and Freqtrade wallet-curve drawdown.

## 11. LLM, forward-only data, and final decision

No LLM output enters the strategy, model, risk sizing, or execution path. A future
LLM may operate only as a one-way shadow observer over delayed, sanitized reports
for anomaly classification, post-trade explanation, and hypotheses for a later
locked cycle. It receives no credentials and its timeout or malformed output cannot
change trading state.

Order flow, OI, taker ratios, and news/sentiment require a later plan after enough
point-in-time immutable history exists. They cannot be backfilled from today's view.

Final state:

- technical/data/source/model/bias failure: `REJECT_PRO_DAY_TRADER_V2`;
- technically valid but performance/sample/stress failure:
  `KEEP_OFFLINE_RESEARCH`;
- every gate passes: `APPROVE_SEPARATE_DRY_RUN` only.

Even approval requires an isolated database, logs, port, healthcheck, monitor, and
resource acceptance. At least 30 continuous dry-run days and 30 valid closed trades
are required before any later human decision. Live trading remains disabled and
profit is never guaranteed.
