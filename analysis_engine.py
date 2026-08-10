# analysis_engine.py

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

from indicators import calc_macd, calc_rsi
from scoring import calc_rebound_score

JST = ZoneInfo("Asia/Tokyo")
THRESHOLD = 1.0
MINIMUM_REQUIRED_ROWS = 26


def get_analysis_executed_at() -> str:
    """分析実行日時を日本時間で返す。"""
    return datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")


def get_trade_date(df: pd.DataFrame) -> str:
    """価格データ最終行の日付を取引日として返す。"""
    return pd.Timestamp(df.index[-1]).strftime("%Y-%m-%d")


def prepare_dataframe(df: pd.DataFrame) -> pd.DataFrame | None:
    """分析用のテクニカル指標を追加したDataFrameを作成する。"""
    if df is None or df.empty:
        return None

    if "Close" not in df.columns:
        return None

    data = df.copy()
    data = data.dropna(subset=["Close"]).ffill()

    if len(data) < MINIMUM_REQUIRED_ROWS:
        return None

    data["25MA"] = data["Close"].rolling(25).mean()
    data["High20"] = data["High"].rolling(20).max()
    data["Low20"] = data["Low"].rolling(20).min()
    data["RSI"] = calc_rsi(data["Close"])
    data["MACD"], data["Signal"] = calc_macd(data["Close"])
    data["25MAタッチ"] = (
        ((data["Close"] - data["25MA"]).abs() / data["25MA"] * 100)
        <= THRESHOLD
    )
    data["20日安値タッチ"] = (
        ((data["Close"] - data["Low20"]).abs() / data["Low20"] * 100)
        <= THRESHOLD
    )
    daily_range = data["High"] - data["Low"]
    data["終値位置(%)"] = (
        (data["Close"] - data["Low"]) / daily_range * 100
    ).where(daily_range > 0, 50.0)
    data["陽線"] = data["Close"] > data["Open"]
    data["反発初動"] = (
        data["20日安値タッチ"]
        & data["陽線"]
        & (data["終値位置(%)"] >= 70)
    )
    data["RSI40以下"] = data["RSI"] <= 40
    data["MACDシグナル以下"] = data["MACD"] <= data["Signal"]

    return data


def create_judgment(
    is_25ma_touch: bool,
    is_box_top_touch: bool,
    is_box_bottom_touch: bool,
    latest_close: float,
    previous_close: float,
    latest_rsi: float,
    latest_macd: float,
    latest_signal: float,
    score: int,
) -> str:
    """テクニカル条件とスコアから表示用の判定文を作る。"""
    judgments = []

    if is_25ma_touch:
        if latest_close > previous_close:
            judgments.append("25MAタッチ＋終値上昇（反発強候補）")
        elif latest_close < previous_close:
            judgments.append("25MAタッチ＋終値下落（反発弱候補・注意）")
        else:
            judgments.append("25MAタッチ＋終値横ばい（様子見）")

    if is_box_top_touch:
        if latest_close > previous_close:
            judgments.append("ボックス上限タッチ＋上昇（上抜け警戒）")
        elif latest_close < previous_close:
            judgments.append("ボックス上限タッチ＋下落（天井候補）")
        else:
            judgments.append("ボックス上限タッチ（天井圏）")

    if is_box_bottom_touch:
        if latest_close > previous_close:
            judgments.append("ボックス下限タッチ＋上昇（底打ち反発候補）")
        elif latest_close < previous_close:
            judgments.append("ボックス下限タッチ＋下落（下抜け警戒）")
        else:
            judgments.append("ボックス下限タッチ（底圏）")

    if latest_rsi <= 25:
        judgments.append(f"RSI {latest_rsi:.1f}（強い売られ過ぎ）")
    elif latest_rsi <= 30:
        judgments.append(f"RSI {latest_rsi:.1f}（売られ過ぎ）")
    elif latest_rsi <= 40:
        judgments.append(f"RSI {latest_rsi:.1f}（やや弱い）")
    elif latest_rsi >= 70:
        judgments.append(f"RSI {latest_rsi:.1f}（買われ過ぎ・警戒）")

    if latest_macd > latest_signal:
        judgments.append("MACDゴールデンクロス（上昇トレンド寄り）")
    elif latest_macd < latest_signal:
        judgments.append("MACDデッドクロス（下落トレンド寄り）")

    if score >= 80:
        judgments.append(f"総合スコア {score}点（強い反発候補）")
    elif score >= 60:
        judgments.append(f"総合スコア {score}点（反発候補）")
    else:
        judgments.append(f"総合スコア {score}点（反発余地あり）")

    return " / ".join(judgments) if judgments else "判定なし"


def analyze_dataframe(
    df: pd.DataFrame,
    ticker: str,
    name: str,
    analysis_executed_at: str | None = None,
) -> tuple[dict | None, pd.DataFrame | None]:
    """
    取得済みの価格DataFrameを分析し、
    分析結果の辞書と指標付きDataFrameを返す。
    """
    data = prepare_dataframe(df)

    if data is None:
        return None, None

    latest_close = float(data["Close"].iloc[-1])
    previous_close = float(data["Close"].iloc[-2])
    latest_ma = float(data["25MA"].iloc[-1])
    latest_high20 = float(data["High20"].iloc[-1])
    latest_low20 = float(data["Low20"].iloc[-1])
    latest_rsi = float(data["RSI"].iloc[-1])
    latest_macd = float(data["MACD"].iloc[-1])
    latest_signal = float(data["Signal"].iloc[-1])

    if pd.isna(latest_ma) or pd.isna(latest_rsi):
        return None, None

    difference = latest_close - previous_close
    change_rate = (difference / previous_close) * 100

    is_25ma_touch = bool(data["25MAタッチ"].iloc[-1])
    is_box_top_touch = (
        abs(latest_close - latest_high20)
        <= latest_high20 * THRESHOLD / 100
    )
    is_box_bottom_touch = bool(data["20日安値タッチ"].iloc[-1])

    score = calc_rebound_score(
        is_25ma_touch=is_25ma_touch,
        is_box_bottom_touch=is_box_bottom_touch,
        rsi=latest_rsi,
        macd=latest_macd,
        signal=latest_signal,
        close_today=latest_close,
        close_yesterday=previous_close,
    )

    judgment = create_judgment(
        is_25ma_touch=is_25ma_touch,
        is_box_top_touch=is_box_top_touch,
        is_box_bottom_touch=is_box_bottom_touch,
        latest_close=latest_close,
        previous_close=previous_close,
        latest_rsi=latest_rsi,
        latest_macd=latest_macd,
        latest_signal=latest_signal,
        score=score,
    )

    if analysis_executed_at is None:
        analysis_executed_at = get_analysis_executed_at()

    result = {
        "分析実行日時": analysis_executed_at,
        "取引日": get_trade_date(data),
        "銘柄コード": ticker,
        "銘柄名": name,
        "終値": round(latest_close, 1),
        "前日比": round(difference, 1),
        "前日比率(%)": round(change_rate, 2),
        "RSI": round(latest_rsi, 1),
        "MACD": round(latest_macd, 3),
        "Signal": round(latest_signal, 3),
        "25MA": round(latest_ma, 1),
        "20日高値": round(latest_high20, 1),
        "20日安値": round(latest_low20, 1),
        "25MAタッチ": is_25ma_touch,
        "20日安値タッチ": is_box_bottom_touch,
        "陽線": bool(data["陽線"].iloc[-1]),
        "終値位置(%)": round(float(data["終値位置(%)"].iloc[-1]), 1),
        "反発初動": bool(data["反発初動"].iloc[-1]),
        "判定": judgment,
        "反発確度スコア": score,
    }

    return result, data


def analyze_ticker(
    ticker: str,
    name: str,
    period: str = "6mo",
    analysis_executed_at: str | None = None,
) -> tuple[dict | None, pd.DataFrame | None]:
    """yfinanceから1銘柄を取得して分析する。"""
    try:
        df = yf.Ticker(ticker).history(period=period)
    except Exception as error:
        print(f"{ticker} データ取得エラー: {error}")
        return None, None

    return analyze_dataframe(
        df=df,
        ticker=ticker,
        name=name,
        analysis_executed_at=analysis_executed_at,
    )
