# update_checker.py
# 200銘柄（日本100＋米国100）対応版
import yfinance as yf
import json
import requests
import os
from datetime import datetime
from tickers import TICKERS   # ← 200銘柄を読み込む

LINE_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_URL = "https://api.line.me/v2/bot/message/push"
USER_ID = "U889b3c025bd9a29b4651833d39a4f7a6"

THRESHOLD = 1.0  # ±1%以内をタッチ判定


def send_line(message: str):
    """LINE Messaging API に通知を送る"""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_TOKEN}"
    }
    data = {"to": USER_ID, "messages": [{"type": "text", "text": message}]}

    try:
        response = requests.post(LINE_URL, headers=headers, json=data)
        if response.status_code != 200:
            print(f"LINE送信エラー: {response.status_code} - {response.text}")
        else:
            print("LINE送信成功")
    except Exception as e:
        print(f"LINE送信例外: {e}")


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


def analyze_ticker(ticker: str):
    """終値・スコア・判定文字をまとめて返す"""
    try:
        df = yf.Ticker(ticker).history(period="6mo").ffill()
    except Exception as e:
        print(f"{ticker} データ取得エラー: {e}")
        return None

    if df.empty:
        print(f"{ticker} データなし")
        return None

    # テクニカル指標
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

    # 判定文字（複数対応）
    judges = []

    if abs(deviation_ma) <= THRESHOLD:
        judges.append("25MAタッチ（反発候補）")

    if abs(latest_close - latest_high20) <= (latest_high20 * THRESHOLD / 100):
        judges.append("ボックス上限タッチ（天井候補）")

    if abs(latest_close - latest_low20) <= (latest_low20 * THRESHOLD / 100):
        judges.append("ボックス下限タッチ（底候補）")

    judge = "・".join(judges) if judges else "判定なし"

    # スコア
    score = calc_score(
        abs(deviation_ma) <= THRESHOLD,
        abs(latest_close - latest_low20) <= (latest_low20 * THRESHOLD / 100),
        latest_rsi,
        latest_macd,
        latest_signal
    )

    return latest_close, score, judge


# JSON読み込み
try:
    with open("update_status.json", "r") as f:
        status = json.load(f)
except FileNotFoundError:
    status = {}

updated_list = []

# 200銘柄をループ
for ticker, name in TICKERS.items():
    result = analyze_ticker(ticker)
    if result is None:
        continue

    new_close, score, judge = result

    # 初回登録
    if ticker not in status:
        status[ticker] = {
            "last_close": new_close,
            "updated": False,
            "last_update_time": None
        }
        continue

    # 終値更新判定
    if abs(new_close - status[ticker]["last_close"]) > 0.01:
        status[ticker]["updated"] = True
        status[ticker]["last_update_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        status[ticker]["last_close"] = new_close

        # 🔥 スコア50以上の銘柄のみ通知（判定文字含む）
        if score >= 50:
            updated_list.append(
                f"{name}（{ticker}）\n"
                f"終値更新：{new_close}\n"
                f"判定：{judge}\n"
                f"反発確度スコア：{score}"
            )
    else:
        status[ticker]["updated"] = False


# JSON保存
try:
    with open("update_status.json", "w") as f:
        json.dump(status, f, indent=4, ensure_ascii=False)
except Exception as e:
    print(f"JSON保存エラー: {e}")
    # GitHub Actions を落とさない
    pass


# LINE通知
try:
    if updated_list:
        send_line("\n\n".join(updated_list))
except Exception as e:
    print(f"LINE通知エラー: {e}")
    pass
