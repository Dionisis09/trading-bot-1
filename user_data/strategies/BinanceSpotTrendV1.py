"""Pre-declared Binance Spot trend-following research strategy.

This strategy is intentionally simple.  Its parameters were fixed before the
first backtest and are documented in ``docs/strategy_research_plan.md``.
It is intended for dry-run research only, not live trading.
"""

from pandas import DataFrame
import talib.abstract as ta

from freqtrade.strategy import IStrategy, informative
from technical import qtpylib


class BinanceSpotTrendV1(IStrategy):
    """Long-only 15m trend reclaim entries inside a positive 1h regime."""

    INTERFACE_VERSION = 3

    can_short = False
    timeframe = "15m"
    process_only_new_candles = True
    # 800 was selected from recursive-analysis, not from PnL.  At 400 candles
    # the 1h EMA200 still varied by about 0.10%; at 799 it was effectively zero.
    startup_candle_count = 800

    # Disable time-based ROI exits in practice. Exits are controlled by the
    # trend-failure signal, the hard stop, and the delayed trailing stop.
    minimal_roi = {"0": 100.0}
    stoploss = -0.06

    trailing_stop = True
    trailing_stop_positive = 0.02
    trailing_stop_positive_offset = 0.04
    trailing_only_offset_is_reached = True

    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False

    order_types = {
        "entry": "limit",
        "exit": "limit",
        "stoploss": "market",
        "stoploss_on_exchange": False,
    }
    order_time_in_force = {"entry": "GTC", "exit": "GTC"}

    @property
    def protections(self):
        """Pause entries after clustered losses or portfolio drawdown."""
        return [
            {
                "method": "CooldownPeriod",
                "stop_duration_candles": 4,
            },
            {
                "method": "StoplossGuard",
                "lookback_period_candles": 48,
                "trade_limit": 2,
                "stop_duration_candles": 12,
                "only_per_pair": False,
            },
            {
                "method": "MaxDrawdown",
                "lookback_period_candles": 96,
                "trade_limit": 4,
                "stop_duration_candles": 24,
                "max_allowed_drawdown": 0.10,
            },
        ]

    @informative("1h")
    def populate_indicators_1h(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """Build the slower market-regime indicators."""
        dataframe["ema50"] = ta.EMA(dataframe, timeperiod=50)
        dataframe["ema200"] = ta.EMA(dataframe, timeperiod=200)
        dataframe["adx"] = ta.ADX(dataframe, timeperiod=14)
        return dataframe

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """Build entry, volatility, and volume indicators on 15m candles."""
        dataframe["ema20"] = ta.EMA(dataframe, timeperiod=20)
        dataframe["ema50"] = ta.EMA(dataframe, timeperiod=50)
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["atr_pct"] = dataframe["atr"] / dataframe["close"]
        dataframe["volume_median_24"] = dataframe["volume"].rolling(24).median()
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """Enter on a 15m EMA reclaim while the 1h regime remains positive."""
        entry_conditions = (
            (dataframe["close_1h"] > dataframe["ema200_1h"])
            & (dataframe["ema50_1h"] > dataframe["ema200_1h"])
            & (dataframe["adx_1h"] > 20.0)
            & (dataframe["ema20"] > dataframe["ema50"])
            & qtpylib.crossed_above(dataframe["close"], dataframe["ema20"])
            & (dataframe["rsi"] > 50.0)
            & (dataframe["rsi"] < 70.0)
            & (dataframe["atr_pct"] > 0.002)
            & (dataframe["atr_pct"] < 0.04)
            & (dataframe["volume"] > dataframe["volume_median_24"])
            & (dataframe["volume"] > 0)
        )

        dataframe.loc[entry_conditions, ["enter_long", "enter_tag"]] = (
            1,
            "trend_reclaim",
        )
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """Exit when the local trend crosses down or the 1h trend materially fails."""
        exit_conditions = (
            qtpylib.crossed_below(dataframe["ema20"], dataframe["ema50"])
            | (dataframe["close_1h"] < dataframe["ema50_1h"])
        ) & (dataframe["volume"] > 0)

        dataframe.loc[exit_conditions, ["exit_long", "exit_tag"]] = (
            1,
            "trend_failure",
        )
        return dataframe
