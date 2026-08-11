# ProDayTraderV1 - Κλειδωμένο Ερευνητικό Πλάνο

## Κατάσταση και όριο αποδείξεων

- Κατάσταση: `LOCKED_BEFORE_FIRST_PRO_DAY_PNL_RUN`.
- Ημερομηνία κλειδώματος: 2026-08-11 (Europe/Athens).
- Μοναδικός υποψήφιος αυτού του κύκλου: `ProDayTraderV1`.
- Δεν επιτρέπονται hyperopt, grid search, αλλαγή threshold, αφαίρεση pair,
  απενεργοποίηση side/setup ή δεύτερος υποψήφιος μετά την εμφάνιση PnL.
- Όλη η διαθέσιμη ιστορία έχει ήδη χρησιμοποιηθεί σε προηγούμενη έρευνα άλλων
  strategies. Συνεπώς τα αποτελέσματα είναι ιστορική robustness evidence, όχι
  sealed holdout, forward evidence, εγγύηση κέρδους ή άδεια live trading.
- Τα ενεργά `DualTrendFuturesV1` και `DualTrendFuturesV2R`, οι βάσεις τους, το
  monitoring continuity και τα ports τους παραμένουν ανέπαφα σε όλη την έρευνα.

## Frozen runtime, universe και περίοδοι

- Runtime: pinned Docker image `freqtradeorg/freqtrade:2026.7` με το digest του
  υφιστάμενου `docker-compose.yml`.
- Exchange/mode: Binance USD-M USDT perpetual futures, isolated margin, 1x.
- Universe, χωρίς μεταγενέστερη αφαίρεση:
  - `BTC/USDT:USDT`
  - `ETH/USDT:USDT`
  - `BNB/USDT:USDT`
- Main timeframe: native 5m candles.
- Informative timeframes: native 15m, 1h και 4h candles.
- Timezone: UTC. Χρησιμοποιούνται μόνο κλεισμένα candles και το νωρίτερο
  θεωρητικό fill είναι στο επόμενο 5m open.
- Download/warm-up coverage: `2020-12-01T00:00:00Z` έως
  `2026-08-02T00:00:00Z`.
- TRAIN: `[2021-01-01, 2024-01-01)`.
- VALIDATION: `[2024-01-01, 2026-01-01)`.
- CURRENT_PARTIAL: `[2026-01-01, 2026-08-01)`.
- Canonical continuous replay: `[2021-01-01, 2026-08-01)`.

## DATA_BLOCKED gate πριν από PnL

Πριν από backtest δημιουργείται manifest με SHA256 του παρόντος plan, strategy,
research config, risk policy και κάθε input data file. Απαιτούνται native futures
αρχεία για 3 pairs x 4 timeframes.

Για κάθε pair/timeframe/split απαιτούνται:

- μηδέν duplicate timestamps·
- μηδέν null/non-finite OHLCV·
- `high >= max(open, close)`, `low <= min(open, close)`, `low > 0`,
  `volume >= 0`·
- χρονική κάλυψη τουλάχιστον 99.95%·
- κανένα undocumented gap μεγαλύτερο από 3 base candles·
- αναγωγή πλήρων 5m bins σε 15m/1h/4h και mismatch-days το πολύ 0.20% με
  προκαθορισμένη numeric tolerance.

Αποτυχία οποιουδήποτε pair δεν επιτρέπει αφαίρεσή του. Η κατάσταση γίνεται
`DATA_BLOCKED` και δεν εκτελείται qualification PnL.

## Κλειδωμένοι κανόνες strategy

### Causal features

- Main 5m: ATR14, ADX14, RSI14, relative volume έναντι του median των 48
  προηγούμενων candles, volume expansion έναντι του mean των 12 προηγούμενων
  candles και candle-delta proxy
  `(close-open) / max(high-low, epsilon) * volume`.
- 15m: EMA20, EMA50, ADX14 και ATR14.
- 1h/4h: EMA50, EMA200, ADX14, ATR14 και Choppiness14.
- Session/day και week VWAP: cumulative μόνο μέσα στο τρέχον UTC anchor.
- Previous day/week high-low: ολοκληρωμένο προηγούμενο period με υποχρεωτικό
  shift μιας περιόδου.
- Rolling volume-profile approximation, 288 κλεισμένων 5m candles: POC ως
  rolling volume-weighted typical price και VAH/VAL ως POC +/- 1.15 weighted
  standard deviations. Πρόκειται ρητά για approximation, όχι exchange profile.
- Market structure: σύγκριση των τελευταίων 12 ολοκληρωμένων 5m bars με τα 12
  αμέσως προηγούμενα για HH/HL ή LH/LL.
- Informative data συγχωνεύονται μόνο με το causal `merge_informative_pair`.
- BTC 4h context εφαρμόζεται μόνο στα ETH/BNB trades.

### Regime και mandatory risk gates

Long regime score (0-2):

1. 4h close > EMA200 και EMA50 > EMA200.
2. 1h close > EMA50 > EMA200 και (`ADX14 >= 18` ή `Choppiness14 <= 61.8`).

Short regime score (0-2), ανεξάρτητος και αυστηρότερος:

1. 4h close < EMA200 και EMA50 < EMA200.
2. 1h close < EMA50 < EMA200, `ADX14 >= 20` και
   `Choppiness14 <= 61.8`.

Για altcoin long απαιτείται BTC 4h close >= 0.99 x EMA200 και BTC EMA50 >=
0.995 x EMA200. Για altcoin short απαιτείται BTC 4h close <= 1.01 x EMA200 και
BTC EMA50 <= 1.005 x EMA200. Για BTC το context gate είναι true.

Κοινά fail-closed gates: finite informative values, volume > 0, 5m ATR/close
στο `[0.0005, 0.025]` και 1h ATR/close στο `[0.001, 0.08]`.

### Πέντε ανεξάρτητες κατηγορίες score

Κάθε κατηγορία δίνει 0-2 πόντους, σύνολο 0-10:

1. Regime: οι δύο κανόνες της αντίστοιχης πλευράς.
2. Location:
   - απόσταση έως session VWAP <= 0.75 ATR ή έως weekly VWAP <= 1 ATR·
   - τιμή μέσα σε VAL-VAH ή απόσταση <= 1 ATR από VAL/VAH ή previous
     day/week high-low.
3. Structure:
   - long: HH και HL, ένας πόντος για καθένα·
   - short: LH και LL, ένας πόντος για καθένα.
4. Trigger:
   - displacement: body/ATR >= 0.45 και close στο άνω 35% του candle για long
     ή στο κάτω 35% για short·
   - ένας από τους τρεις fixed setups παρακάτω.
5. Participation:
   - relative volume >= 1.15·
   - volume >= 1.20 x previous-12 mean ή side-consistent candle-delta ratio με
     απόλυτη τιμή >= 0.10.

Long entry: regime >= 1, location >= 1, structure >= 1, trigger = 2,
participation >= 1, BTC/risk gates true και total score >= 7.

Short entry: regime = 2, location >= 1, structure >= 1, trigger = 2,
participation >= 1, BTC/risk gates true και total score >= 8.

### Τρία fixed setups

1. `trend_pullback`: touch/reclaim της 15m EMA20 ή session VWAP, κλείσιμο προς
   την πλευρά του regime και επιβεβαίωση του προηγούμενου 5m high/low.
2. `breakout_retest`: το προηγούμενο candle έκλεισε πέρα από το shifted
   48-candle high/low και το τρέχον candle έκανε retest εντός 0.20% και έκλεισε
   ξανά πέρα από το level.
3. `liquidity_sweep`: sweep του shifted 24-candle low/high, reclaim στο ίδιο
   candle και wick τουλάχιστον 1.25 x το real body.

Αν συμπίπτουν setups, η μοναδική deterministic tag προτεραιότητα είναι:
`liquidity_sweep`, μετά `breakout_retest`, μετά `trend_pullback`. Κάθε accepted
trade γράφει setup, side και component scores στο `enter_tag`. Κάθε 5m row
γράφει numeric rejection bitmask για data, volatility, regime, BTC context,
location, structure, trigger, participation και total score, ώστε η απόρριψη
να είναι εξηγήσιμη χωρίς per-candle log spam.

### Position sizing, stops και exits

- `position_adjustment_enable = False`: καμία martingale ή DCA.
- Hard emergency stop: `-4%`.
- Risk budget ανά trade: 0.25% του dry-run wallet.
- Sizing stop distance: clamp του `2 x ATR/close` στο `[0.75%, 3%]`.
- Stake: minimum των proposed stake, exchange max, 10% wallet exposure και
  `0.25% wallet / stop_distance`. Invalid/missing input ή minimum exchange stake
  πάνω από το ασφαλές stake επιστρέφει 0, χωρίς fallback σε proposed stake.
- Dynamic structure/ATR stop:
  - long candidate = min(last structure low - 0.25 ATR,
    current rate - 1.75 ATR)·
  - short candidate = max(last structure high + 0.25 ATR,
    current rate + 1.75 ATR)·
  - η απόσταση περιορίζεται στο `[0.75%, 3%]` και το Freqtrade επιτρέπεται μόνο
    να τη σφίγγει, όχι να τη διευρύνει.
- Profit protection: στο +0.8% προστασία περίπου break-even, στο +1.5% μέγιστη
  απόσταση 0.6% από current rate και στο +2.5% μέγιστη απόσταση 0.8%.
- Time stop: έξοδος μετά από 180 λεπτά όταν profit <= 0 και υποχρεωτική έξοδος
  μετά από 720 λεπτά.
- Structure exit: long κάτω από 15m EMA50 μαζί με LL, short πάνω από 15m EMA50
  μαζί με HH.
- Protections: cooldown 3 candles, StoplossGuard lookback 144/trade-limit 3/
  stop 48 candles, MaxDrawdown lookback 2016/trade-limit 10/stop 288 candles/
  maximum drawdown 8%. Τα backtests τρέχουν πάντα με protections enabled.
- Leverage callback επιστρέφει πάντα 1.0 και margin mode είναι isolated.

## Derivatives και order-flow evidence boundary

Τα δημόσια Binance `openInterestHist` και `takerlongshortRatio` κρατούν περίπου
έναν μήνα ιστορίας. Ο credential-free collector αρχίζει τώρα, κάνει validated
append/upsert και αποθηκεύει manifest/freshness. Τα δεδομένα είναι shadow-only
στο V1 και δεν επηρεάζουν ιστορικά entries του 2021-2025.

Το Freqtrade order-flow είναι beta και απαιτεί raw trades/περισσότερη RAM.
Επιτρέπεται μόνο περιορισμένο local BTC/5m benchmark με μικρό cache. Δεν
ενεργοποιείται στο VPS ούτε γίνεται decision gate σε αυτόν τον κύκλο. Μελλοντική
χρήση OI/taker/order-flow απαιτεί νέο προ-κλειδωμένο research cycle αφού
συσσωρευτεί point-in-time forward history.

## Διαδοχική qualification και walk-forward

1. Freeze hashes plan/strategy/config/risk/data.
2. TRAIN εκτελείται μία φορά. Αποτυχία κλειδώνει την απόφαση σε
   `KEEP_OFFLINE_RESEARCH`· μεταγενέστερα periods επιτρέπονται μόνο ως
   μη-qualifying diagnostics και δεν μπορούν να ξανανοίξουν την απόφαση.
3. Μόνο TRAIN pass ξεκλειδώνει μία qualification εκτέλεση VALIDATION.
4. Μόνο TRAIN+VALIDATION pass ξεκλειδώνει CURRENT_PARTIAL qualification.
5. Annual expanding diagnostics: test years 2022, 2023, 2024, 2025 και 2026p,
   με όλη την προηγούμενη ιστορία μόνο ως warm-up/state και χωρίς calibration.
6. Quarterly OOS diagnostics: 2024-Q1 έως 2025-Q4, χωρίς calibration μεταξύ
   folds.
7. Τα year/quarter metrics της canonical απόφασης προέρχονται από το continuous
   trade stream, χωρίς wallet/protection reset. Standalone reset folds
   επισημαίνονται μόνο ως diagnostics και δεν αθροίζονται.

## Κλειδωμένα performance και sample gates

### TRAIN

- trades >= 180, return > 0, PF >= 1.20, canonical Freqtrade wallet-curve
  max drawdown <= 15%, return/drawdown >= 0.75.

### VALIDATION

- trades >= 120, return > 0, PF >= 1.50, drawdown <= 12%,
  return/drawdown >= 1.00.
- Κάθε 2024 και 2025: trades >= 40, return > 0, PF >= 1.15, DD <= 10%.
- Κάθε pair: trades >= 25, PF >= 0.90, return > -2%· τουλάχιστον 2/3 pairs
  positive· μεγαλύτερο positive-pair contribution <= 60%.
- Μεγαλύτερο winning-trade contribution <= 20% του gross positive PnL.
- Long και short ξεχωριστά: trades >= 40, net > 0, PF >= 1.05.

### CURRENT_PARTIAL

- trades >= 20, return >= 0, PF >= 1.10, DD <= 8%.

### Year/quarter stability

- Στα πλήρη 2021-2025 του continuous stream: τουλάχιστον 4/5 positive years,
  median yearly PF >= 1.20 και worst full-year return > -3%.
- Τουλάχιστον 12/20 positive full quarters overall και 5/8 positive validation
  quarters· worst full-quarter return > -3%.

### Regimes

Το regime κάθε entry ταξινομείται μόνο από το τελευταίο κλεισμένο BTC 4h:
bull όταν close > EMA200, EMA50 > EMA200 και ADX14 >= 20· bear συμμετρικά·
sideways αλλιώς.

- Bull και bear: τουλάχιστον 30 validation trades το καθένα.
- Κάθε regime με >= 20 trades: net >= 0 και PF >= 1.00.
- Κάθε regime ανεξαρτήτως count: return > -1%.
- Sideways μπορεί να έχει 0 trades ως έγκυρη αποχή, αλλά time share και rejection
  counts αναφέρονται.

## Execution-cost stress

Baseline fee: 5 bps ανά side συν recorded funding.

- Moderate: +2 fee bps/side, 5 slippage bps/side, 2 one-way latency bps,
  funding x1.5.
- Severe: +10 fee bps/side, 15 slippage bps/side, 5 one-way latency bps,
  funding x3.

VALIDATION moderate: return > 0, PF >= 1.20, DD <= 13%, return/DD >= 0.75.
VALIDATION severe: return > 0, PF >= 1.05, DD <= 15%, return/DD >= 0.50.

Ανά validation year: moderate net > 0 και PF >= 1.10· severe return > -2% και
PF >= 0.95. Χρησιμοποιούνται τα ίδια raw trades και η ίδια χρονική σειρά, χωρίς
outcome-dependent repricing.

## Bias, recursion και source reconciliation

- `lookahead-analysis` στη validation περίοδο: baseline signals >= 100,
  `has_bias=false`, μηδέν biased entry/exit/indicator και αντιπροσώπευση των
  sides/setups που ισχυρίζεται το backtest. Μη ενεργοποιημένο signal δεν
  θεωρείται ελεγμένο.
- Fixed recursive candidate counts:
  `[199, 399, 799, 1599, 3199, 6399, 12799]`. Το strategy startup είναι 3199.
  Κάθε decision-critical indicator πρέπει να έχει absolute variance <= 0.01%
  και μηδέν signal differences στο επιλεγμένο startup. Αλλιώς FAIL· το startup
  δεν αλλάζει μετά το PnL.
- Κάθε ZIP sanitizes πρώτα, περνά `testzip`, και μετά hash/evaluation.
- Το manifest περιέχει SHA256 plan, strategy, config, risk policy, data και
  explicit artifact filenames. Απαγορεύεται επιλογή artifact με mtime/latest.
- Embedded strategy source πρέπει να έχει το frozen workspace hash. Τα
  non-secret config fields πρέπει να συμφωνούν με futures/isolated/1x,
  wallet/stake/max-open=2, fee, universe, timeframes και timerange.
- Ανεξάρτητη reconciliation: exact trade/win/loss/draw/long/short/pair counts,
  absolute-profit tolerance 1e-6 και PF tolerance 1e-12. Canonical drawdown είναι
  το Freqtrade `max_drawdown_account`; το independently closed-trade realized DD
  αναφέρεται χωριστά και δεν παρουσιάζεται ψευδώς ως το ίδιο metric.

## Τελική απόφαση

- Technical/data/source/bias failure: `REJECT_PRO_DAY_TRADER`.
- Technically valid αλλά performance/sample gate failure:
  `KEEP_OFFLINE_RESEARCH`.
- Μόνο αν περάσουν όλα τα locked gates:
  `APPROVE_SEPARATE_DRY_RUN`.

Ακόμη και το `APPROVE_SEPARATE_DRY_RUN` επιτρέπει μόνο τρίτο credential-free
dry-run με ξεχωριστή SQLite/port/health/monitoring. Δεν επιτρέπει live trading,
API keys, automatic promotion ή αντικατάσταση του V2R.
