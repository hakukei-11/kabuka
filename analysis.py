# analysis.py
import yfinance as yf
import pandas as pd
from indicators import calc_rsi, calc_macd
from scoring import calc_score

THRESHOLD = 1.0  # ±1%以内をタッチ判定

def analyze_tickers(tickers):
    results = []
    all_data = {}

    for ticker, name in tickers.items():
        df = yf.Ticker(ticker).history(period="6mo")
        if df is None or df.empty:
            continue

        df = df.ffill()
        df['25MA'] = df['Close'].rolling(25).mean()
        df['High20'] = df['High'].rolling(20).max()
        df['Low20'] = df['Low'].rolling(20).min()

        latest_close = df['Close'].iloc[-1]
        latest_ma = df['25MA'].iloc[-1]
        latest_high20 = df['High20'].iloc[-1]
        latest_low20 = df['Low20'].iloc[-1]

        deviation_ma = ((latest_close - latest_ma) / latest_ma) * 100
        box_top_touch = abs(latest_close - latest_high20) <= (latest_high20 * THRESHOLD / 100)
        box_bottom_touch = abs(latest_close - latest_low20) <= (latest_low20 * THRESHOLD / 100)

        df['RSI'] = calc_rsi(df['Close'])
        df['MACD'], df['Signal'] = calc_macd(df['Close'])
        latest_rsi = df['RSI'].iloc[-1]
        latest_macd = df['MACD'].iloc[-1]
        latest_signal = df['Signal'].iloc[-1]

        score = calc_score(
            abs(deviation_ma) <= THRESHOLD,
            box_bottom_touch,
            latest_rsi,
            latest_macd,
            latest_signal
        )

        judge = ""
        if abs(deviation_ma) <= THRESHOLD:
            judge = "25MAタッチ（反発候補）"
        if box_top_touch:
            judge = "ボックス上限タッチ（天井候補）"
        if box_bottom_touch:
            judge = "ボックス下限タッチ（底候補）"

        results.append({
            "銘柄コード": ticker,
            "銘柄名": name,
            "判定": judge,
            "終値": round(latest_close, 1),
            "RSI": round(latest_rsi, 1),
            "MACD": round(latest_macd, 3),
            "Signal": round(latest_signal, 3),
            "反発確度スコア": score
        })

        all_data[ticker] = df

    return results, all_data
