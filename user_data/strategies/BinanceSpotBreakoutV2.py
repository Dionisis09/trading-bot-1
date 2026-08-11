"""Pre-declared Donchian breakout trial for Binance Spot dry-run research."""

from pandas import DataFrame
import talib.abstract as ta

from freqtrade.strategy import IStrategy, informative
from technical import qtpylib


class BinanceSpotBreakoutV2(IStrategy):
    """Long-only 12h breakout entries inside a positive 1h market regime."""

    INTERFACE_VERSION = 3

    can_short = False
    timeframe = "15m"
    process_only_new_candles = True
    startup_candle_count = 800

    minimal_roi = {"0": 100.0}
    stoploss = -0.07

    trailing_stop = True
    trailing_stop_positive = 0.025
    trailing_stop_positive_offset = 0.06
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
        return [
            {"method": "CooldownPeriod", "stop_duration_candles": 4},
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
        dataframe["ema50"] = ta.EMA(dataframe, timeperiod=50)
        dataframe["ema200"] = ta.EMA(dataframe, timeperiod=200)
        dataframe["adx"] = ta.ADX(dataframe, timeperiod=14)
        return dataframe

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["atr_pct"] = dataframe["atr"] / dataframe["close"]
        dataframe["volume_median_24"] = dataframe["volume"].rolling(24).median()

        # Shift one candle so the active candle never contributes to its own
        # breakout or exit threshold.
        dataframe["breakout_high_96"] = dataframe["high"].rolling(96).max().shift(1)
        dataframe["channel_low_48"] = dataframe["low"].rolling(48).min().shift(1)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        entry_conditions = (
            (dataframe["close_1h"] > dataframe["ema200_1h"])
            & (dataframe["ema50_1h"] > dataframe["ema200_1h"])
            & (dataframe["adx_1h"] > 20.0)
            & qtpylib.crossed_above(dataframe["close"], dataframe["breakout_high_96"])
            & (dataframe["rsi"] > 55.0)
            & (dataframe["rsi"] < 80.0)
            & (dataframe["atr_pct"] > 0.002)
            & (dataframe["atr_pct"] < 0.05)
            & (dataframe["volume"] > dataframe["volume_median_24"])
            & (dataframe["volume"] > 0)
        )

        dataframe.loc[entry_conditions, ["enter_long", "enter_tag"]] = (
            1,
            "donchian_breakout_96",
        )
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        exit_conditions = (
            qtpylib.crossed_below(dataframe["close"], dataframe["channel_low_48"])
            | (dataframe["close_1h"] < dataframe["ema50_1h"])
        ) & (dataframe["volume"] > 0)

        dataframe.loc[exit_conditions, ["exit_long", "exit_tag"]] = (
            1,
            "channel_or_regime_failure",
        )
        return dataframe

