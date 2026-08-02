# export_data.py
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import yfinance as yf

from tickers import TICKERS

LINE_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_URL = "https://api.line.me/v2/bot/message/push"
USER_ID = "U889b3c025bd9a29b4651833d39a4f7a6"

THRESHOLD = 1.0
JST = ZoneInfo("Asia/Tokyo")


def send_line(message: str):
    """LINE Messaging APIへ通知を送信する。"""
    if not LINE_TOKEN:
        print("LINE_CHANNEL_ACCESS_TOKEN が未設定のため、LINE通知をスキップします。")
        return

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_TOKEN}",
    }
    data = {
        "to": USER_ID,
        "messages": [
            {
                "type": "text",
                "text": message,
            }
        ],
    }

    try:
        response = requests.post(
            LINE_URL,
            headers=headers,
            json=data,
            timeout=15,
        )
        response.raise_for_status()
        print("LINE送信成功")
    except requests.RequestException as error:
        print(f"LINE送信エラー: {error}")


def calc_rsi(series, period=14):
    """RSIを計算する。"""
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)

    ma_up = up.rolling(window=period).mean()
    ma_down = down.rolling(window=period).mean()

    return 100 - (100 / (1 + (ma_up / ma_down)))


def calc_macd(series):
    """MACDとシグナルを計算する。"""
    ema12 = series.ewm(span=12, adjust=False).mean()
    ema26 = series.ewm(span=26, adjust=False).mean()

    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()

    return macd, signal


def calc_score(is_25ma_touch, is_box_bottom_touch, rsi, macd, signal):
    """反発候補のスコアを計算する。"""
    score = 0

    if is_25ma_touch:
        score += 30

    if is_box_bottom_touch:
        score += 30

    if rsi <= 30:
        score += 20
    elif rsi <= 40:
        score += 10

    if macd > signal:
        score += 20

    return score


def get_trade_date(df):
    """
    yfinanceから取得した価格データの最終行の日付を、
    分析対象の取引日として返す。
    """
    return pd.Timestamp(df.index[-1]).strftime("%Y-%m-%d")


def analyze(ticker, analysis_executed_at):
    """1銘柄の終値・指標・判定・スコアを返す。"""
    try:
        df = yf.Ticker(ticker).history(period="6mo").ffill()
    except Exception as error:
        print(f"{ticker} データ取得エラー: {error}")
        return None

    if df.empty or len(df) < 26:
        print(f"{ticker} は分析に必要な価格データが不足しています。")
        return None

    df["25MA"] = df["Close"].rolling(25).mean()
    df["High20"] = df["High"].rolling(20).max()
    df["Low20"] = df["Low"].rolling(20).min()
    df["RSI"] = calc_rsi(df["Close"])
    df["MACD"], df["Signal"] = calc_macd(df["Close"])

    latest_close = df["Close"].iloc[-1]
    latest_ma = df["25MA"].iloc[-1]
    latest_high20 = df["High20"].iloc[-1]
    latest_low20 = df["Low20"].iloc[-1]
    latest_rsi = df["RSI"].iloc[-1]
    latest_macd = df["MACD"].iloc[-1]
    latest_signal = df["Signal"].iloc[-1]

    if pd.isna(latest_ma) or pd.isna(latest_rsi):
        print(f"{ticker} は指標計算に必要な価格データが不足しています。")
        return None

    deviation_ma = ((latest_close - latest_ma) / latest_ma) * 100

    is_25ma_touch = abs(deviation_ma) <= THRESHOLD
    is_box_top_touch = (
        abs(latest_close - latest_high20)
        <= latest_high20 * THRESHOLD / 100
    )
    is_box_bottom_touch = (
        abs(latest_close - latest_low20)
        <= latest_low20 * THRESHOLD / 100
    )

    judges = []

    if is_25ma_touch:
        judges.append("25MAタッチ（反発候補）")

    if is_box_top_touch:
        judges.append("ボックス上限タッチ（天井候補）")

    if is_box_bottom_touch:
        judges.append("ボックス下限タッチ（底候補）")

    judge = "・".join(judges) if judges else "判定なし"

    score = calc_score(
        is_25ma_touch,
        is_box_bottom_touch,
        latest_rsi,
        latest_macd,
        latest_signal,
    )

    return {
        "分析実行日時": analysis_executed_at,
        "取引日": get_trade_date(df),
        "銘柄コード": ticker,
        "銘柄名": TICKERS[ticker],
        "終値": round(latest_close, 1),
        "RSI": round(latest_rsi, 1),
        "MACD": round(latest_macd, 3),
        "Signal": round(latest_signal, 3),
        "判定": judge,
        "反発確度スコア": score,
    }


def main():
    """全銘柄を分析し、日次CSVとして保存する。"""
    now_jst = datetime.now(JST)
    analysis_executed_at = now_jst.strftime("%Y-%m-%d %H:%M:%S")

    results = []

    for ticker in TICKERS:
        result = analyze(ticker, analysis_executed_at)

        if result is not None:
            results.append(result)

    if not results:
        raise RuntimeError("保存対象となる分析結果がありません。")

    year = now_jst.strftime("%Y")
    month = now_jst.strftime("%m")
    day = now_jst.strftime("%d")

    folder_path = f"data/{year}/{month}"
    file_path = f"{folder_path}/data_{year}{month}{day}.csv"

    os.makedirs(folder_path, exist_ok=True)

    columns = [
        "分析実行日時",
        "取引日",
        "銘柄コード",
        "銘柄名",
        "終値",
        "RSI",
        "MACD",
        "Signal",
        "判定",
        "反発確度スコア",
    ]

    result_df = pd.DataFrame(results, columns=columns)
    result_df.to_csv(
        file_path,
        index=False,
        encoding="utf-8-sig",
    )

    print(f"CSV保存完了: {file_path}")
    print(f"分析実行日時: {analysis_executed_at}")

    send_line(
        "株価分析CSVを保存しました。\n"
        f"ファイル: {file_path}\n"
        f"分析実行日時: {analysis_executed_at}"
    )


if __name__ == "__main__":
    main()