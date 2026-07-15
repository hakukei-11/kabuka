# export_data.py（CSV保存対応版）
import yfinance as yf
import json
import requests
import os
from datetime import datetime
import pandas as pd
from tickers import TICKERS

LINE_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_URL = "https://api.line.me/v2/bot/message/push"
USER_ID = "U889b3c025bd9a29b4651833d39a4f7a6"

THRESHOLD = 1.0


def send_line(message: str):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_TOKEN}"
    }
    data = {"to": USER_ID, "messages": [{"type": "text", "text": message}]}
    try:
        requests.post(LINE_URL, headers=headers, json=data)
    except Exception as e:
        print(f"LINE送信エラー: {e}")


def calc_rsi(series, period=14):
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    ma_up = up.rolling(window=period).mean()
    ma_down = down.rolling(window=period).mean()
    return 100 - (100 / (1 + (ma_up / ma_down)))


def calc_macd(series):
    ema12 = series.ewm(span=12, adjust=False).mean()
    ema26 = series.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    return macd, signal


def calc_score(is_25ma_touch, is_box_bottom_touch, rsi, macd, signal):
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


def analyze(ticker):
    try:
        df = yf.Ticker(ticker).history(period="6mo").ffill()
    except Exception as e:
        print(f"{ticker} データ取得エラー: {e}")
        return None

    if df.empty or len(df) < 2:
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

    deviation_ma = ((latest_close - latest_ma) / latest_ma) * 100

    judges = []
    if abs(deviation_ma) <= THRESHOLD:
        judges.append("25MAタッチ（反発候補）")
    if abs(latest_close - latest_high20) <= (latest_high20 * THRESHOLD / 100):
        judges.append("ボックス上限タッチ（天井候補）")
    if abs(latest_close - latest_low20) <= (latest_low20 * THRESHOLD / 100):
        judges.append("ボックス下限タッチ（底候補）")

    judge = "・".join(judges) if judges else "判定なし"

    score = calc_score(
        abs(deviation_ma) <= THRESHOLD,
        abs(latest_close - latest_low20) <= (latest_low20 * THRESHOLD / 100),
        latest_rsi,
        latest_macd,
        latest_signal
    )

    return {
        "銘柄コード": ticker,
        "銘柄名": TICKERS[ticker],
        "終値": round(latest_close, 1),
        "RSI": round(latest_rsi, 1),
        "MACD": round(latest_macd, 3),
        "Signal": round(latest_signal, 3),
        "判定": judge,
        "反発確度スコア": score
    }


# === 全銘柄分析 ===
results = []
for ticker in TICKERS.keys():
    res = analyze(ticker)
    if res:
        results.append(res)

# === CSV保存 ===
today = datetime.now()
year = today.strftime("%Y")
month = today.strftime("%m")
day = today.strftime("%d")
folder_path = f"data/{year}/{month}"
os.makedirs(folder_path, exist_ok=True)
file_path = f"{folder_path}/data_{year}{month}{day}.csv"

df = pd.DataFrame(results)
df.to_csv(file_path, index=False, encoding="utf-8-sig")

print(f"✅ CSV保存完了: {file_path}")

# === LINE通知 ===
send_line(f"✅ 株価分析CSVを保存しました。\n{file_path}")
