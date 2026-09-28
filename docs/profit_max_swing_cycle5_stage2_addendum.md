# Profit-Max Swing Cycle 5 - stage 2 recovery addendum

Status: `LOCKED_BEFORE_VALIDATION_PNL_PARSE`. No TRAIN or VALIDATION rerun is permitted.

TRAIN sanitizer/integrity passed and its exact final ZIP is SHA256 `9322c63edc16c4d561b1ee542fd7e689078ab3e8621235c8d779c6ead4ce7dea`. TRAIN gates permitted the already completed VALIDATION run. The immediate validation sanitizer failed only at Windows atomic replace with `WinError 5`.

Stage 2 uses only:

- validation receipt SHA256 `638718e42026e2abe1d4ff5f966ab8512b8c5099e74c49da5938dc4dbfa3f181`
- validation metadata SHA256 `7f17732b65ac82ef44ee7153d26e1013e57bed66314f951326ff8760dd227b1f`
- validation ZIP SHA256 `a118650371ebc44eeac28b588607c6aecefac583578de970e4df6f4857067387`

The established sanitizer may be retried on the same exact ZIP after a short filesystem-release delay, at most five times. No PnL is parsed before sanitizer exit 0 and ZIP integrity. CURRENT_PARTIAL and CONTINUOUS retain the original frozen commands; their sanitizers may use the same bounded same-file retry. No backtest itself may be retried.
