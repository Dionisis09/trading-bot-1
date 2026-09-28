# ProfitMax Daily + V5 Ensemble Cycle 2 — Technical correction

Status: `LOCKED_BEFORE_PNL_PARSE`. Cycle 1 stopped before parsing any PnL because its embedded-config validator allowed only blank credential fields, while the established archive sanitizer stores the exact safe marker `REDACTED`.

Cycle 2 changes only that validation predicate: exchange key and secret must each be either an empty string or the exact string `REDACTED`. No secret value is read or emitted. The two archives, component strategies, all portfolio math, gates, splits and decisions remain byte-for-byte/semantically identical to the Cycle 1 locked plan. Live trading remains unauthorized.

