import yfinance as yf
import json
import requests
import os
from datetime import datetime

LINE_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_URL = "https://api.line.me/v2/bot/message/push"
USER_ID = "U889b3c025bd9a29b4651833d39a4f7a6"

TICKERS = ["7974.T", "6501.T", "AAPL", "MSFT"]
THRESHOLD = 1.0  # ±1%以内をタッチ判定


def send_line(message: str):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_TOKEN}"
    }
    data = {"to": USER_ID, "messages": [{"type": "text", "text": message}]}
    response = requests.post(LINE_URL, headers=headers, json=data)
    if response.status_code != 200:
        print(f"LINE送信エラー: {response.status_code} - {response.text}")
    else:
        print("LINE送信成功")


def calc_rsi(series, period=14):
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    ma_up = up.rolling(window=period).mean()
    ma_down = down.rolling(window=period).mean()
    rsi = 100 - (100 / (1 + (ma_up / ma_down)))
    return rsi


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


def get_close(ticker: str) -> float | None:
    df = yf.Ticker(ticker).history(period="6mo").ffill()
    if df.empty:
        return None

    df["25MA"] = df["Close"].rolling(25).mean()
    df["High20"] = df["High"].rolling(20).max()
    df["Low20"] = df["Low"].rolling(20).min()
    df["RSI"] = calc_rsi(df["Close"])
    df["MACD"], df["Signal"] = calc_macd(df["Close"])

    latest_close = df["Close"].iloc[-1]
    latest_ma = df["25MA"].iloc[-1]
    latest_low20 = df["Low20"].iloc[-1]
    latest_rsi = df["RSI"].iloc[-1]
    latest_macd = df["MACD"].iloc[-1]
    latest_signal = df["Signal"].iloc[-1]

    deviation_ma = ((latest_close - latest_ma) / latest_ma) * 100
    box_bottom_touch = abs(latest_close - latest_low20) <= (latest_low20 * THRESHOLD / 100)

    score = calc_score(abs(deviation_ma) <= THRESHOLD, box_bottom_touch, latest_rsi, latest_macd, latest_signal)
    return latest_close, score


# JSON読み込み
try:
    with open("update_status.json", "r") as f:
        status = json.load(f)
except FileNotFoundError:
    status = {}

updated_list = []

for ticker in TICKERS:
    result = get_close(ticker)
    if result is None:
        continue

    new_close, score = result

    if ticker not in status:
        status[ticker] = {"last_close": new_close, "updated": False, "last_update_time": None}
        continue

    if abs(new_close - status[ticker]["last_close"]) > 0.01:
        status[ticker]["updated"] = True
        status[ticker]["last_update_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        status[ticker]["last_close"] = new_close

        # 🔥 スコアが50以上の銘柄のみ通知
        if score >= 50:
            updated_list.append(f"{ticker} 終値更新 → {new_close}（反発確度スコア: {score}）")
    else:
        status[ticker]["updated"] = False


# JSON保存
with open("update_status.json", "w") as f:
    json.dump(status, f, indent=4, ensure_ascii=False)

# LINE通知
if updated_list:
    send_line("\n".join(updated_list))
