#!/usr/bin/env python3
"""Freeze a public, credential-free Binance USD-M universe before PnL."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "user_data/reports/profit_max_liquid50_cycle1/universe_selection.json"
EXCHANGE_INFO = "https://fapi.binance.com/fapi/v1/exchangeInfo"
TICKER_24H = "https://fapi.binance.com/fapi/v1/ticker/24hr"
CUTOFF_MS = 1_609_459_200_000  # 2021-01-01T00:00:00Z
COUNT = 50


def fetch(url: str) -> tuple[bytes, object]:
    request = Request(url, headers={"User-Agent": "profit-max-public-universe/1.0"})
    with urlopen(request, timeout=30) as response:
        payload = response.read()
    return payload, json.loads(payload)


def main() -> int:
    if OUTPUT.exists():
        raise SystemExit(f"UNIVERSE_BLOCKED: immutable output exists: {OUTPUT}")
    info_bytes, info = fetch(EXCHANGE_INFO)
    ticker_bytes, tickers = fetch(TICKER_24H)
    ticker_map = {row["symbol"]: row for row in tickers}
    eligible = []
    for symbol in info["symbols"]:
        name = symbol["symbol"]
        if not (
            symbol["status"] == "TRADING"
            and symbol["contractType"] == "PERPETUAL"
            and symbol["quoteAsset"] == "USDT"
            and int(symbol["onboardDate"]) <= CUTOFF_MS
            and name in ticker_map
        ):
            continue
        eligible.append(
            {
                "symbol": name,
                "freqtrade_pair": f"{symbol['baseAsset']}/USDT:USDT",
                "onboard_date_utc": datetime.fromtimestamp(int(symbol["onboardDate"]) / 1000, timezone.utc).isoformat(),
                "quote_volume_24h_usdt": float(ticker_map[name]["quoteVolume"]),
            }
        )
    eligible.sort(key=lambda row: (-row["quote_volume_24h_usdt"], row["symbol"]))
    selected = eligible[:COUNT]
    if len(selected) != COUNT or len({row["symbol"] for row in selected}) != COUNT:
        raise SystemExit("UNIVERSE_BLOCKED: insufficient or duplicate eligible symbols")
    payload = {
        "schema_version": "1.0",
        "cycle": "profit_max_liquid50_cycle1",
        "status": "FROZEN_BEFORE_DATA_AND_PNL",
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "selection_policy": {
            "exchange": "Binance USD-M",
            "status": "TRADING",
            "contract_type": "PERPETUAL",
            "quote_asset": "USDT",
            "onboard_not_after_utc": "2021-01-01T00:00:00Z",
            "rank": "descending current public 24h quoteVolume, symbol tie-break",
            "count": COUNT,
            "survivorship_bias": "Current-active universe excludes delisted historical contracts; historical results are conditional and cannot be presented as survivor-free.",
        },
        "sources": {
            "exchange_info": {"url": EXCHANGE_INFO, "sha256": hashlib.sha256(info_bytes).hexdigest()},
            "ticker_24h": {"url": TICKER_24H, "sha256": hashlib.sha256(ticker_bytes).hexdigest()},
        },
        "eligible_count": len(eligible),
        "selected": selected,
        "pnl_evaluated": False,
        "live_trading_authorized": False,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(temporary, OUTPUT)
    print(json.dumps({"status": payload["status"], "selected": len(selected), "minimum_quote_volume": selected[-1]["quote_volume_24h_usdt"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
