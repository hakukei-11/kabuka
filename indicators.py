# indicators.py

from math import isfinite

import pandas as pd


def calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """RSIを計算する。"""
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)

    average_gain = up.rolling(window=period).mean()
    average_loss = down.rolling(window=period).mean()

    return 100 - (100 / (1 + (average_gain / average_loss)))


def calc_macd(
    series: pd.Series,
    short_period: int = 12,
    long_period: int = 26,
    signal_period: int = 9,
) -> tuple[pd.Series, pd.Series]:
    """MACDとシグナルを計算する。"""
    short_ema = series.ewm(span=short_period, adjust=False).mean()
    long_ema = series.ewm(span=long_period, adjust=False).mean()

    macd = short_ema - long_ema
    signal = macd.ewm(span=signal_period, adjust=False).mean()

    return macd, signal


def calc_atr(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> pd.Series:
    """Wilder ATR。初回はperiod本のTR平均、以後は平滑化して更新する。

    先頭足のTRは高値−安値。欠損は補完せず、連続する有効TRが
    period本揃うまで空欄とする。欠損後も同じ条件で再初期化する。
    """
    if isinstance(period, bool) or not isinstance(period, int) or period < 1:
        raise ValueError("ATRの期間は1以上の整数を指定してください。")

    prices = pd.concat({"High": high, "Low": low, "Close": close}, axis=1)
    prices = prices.replace([float("inf"), float("-inf")], float("nan"))
    previous_close = prices["Close"].shift(1)
    true_range = pd.concat(
        [
            prices["High"] - prices["Low"],
            (prices["High"] - previous_close).abs(),
            (prices["Low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1, skipna=False)
    if not true_range.empty:
        true_range.iloc[0] = prices["High"].iloc[0] - prices["Low"].iloc[0]
    valid = prices.notna().all(axis=1) & (prices["High"] >= prices["Low"])
    true_range = true_range.where(valid)

    values = []
    initial_total = 0.0
    initial_count = 0
    previous_atr = None
    for value in true_range:
        if pd.isna(value) or not isfinite(value):
            initial_total = 0.0
            initial_count = 0
            previous_atr = None
            values.append(float("nan"))
            continue
        if previous_atr is None:
            initial_total += float(value)
            initial_count += 1
            if initial_count < period:
                values.append(float("nan"))
                continue
            previous_atr = initial_total / period
        else:
            previous_atr = (previous_atr * (period - 1) + float(value)) / period
        values.append(previous_atr)

    return pd.Series(values, index=prices.index, name=f"ATR{period}", dtype=float)
