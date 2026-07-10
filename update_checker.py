# update_checker.py
import yfinance as yf
import json
from datetime import datetime

TICKERS = ["7974.T", "6501.T", "AAPL", "MSFT"]  # ← 任意の銘柄を追加

def get_close(ticker):
    df = yf.Ticker(ticker).history(period="2d")
    df = df.ffill()
    return float(df["Close"].iloc[-1])

# 前回の終値を読み込み
try:
    with open("update_status.json", "r") as f:
        status = json.load(f)
except:
    status = {}

updated = False

for ticker in TICKERS:
    new_close = get_close(ticker)

    # 初回 or 前回値がない場合
    if ticker not in status:
        status[ticker] = {
            "last_close": new_close,
            "updated": False,
            "last_update_time": None
        }
        continue

    # 差分比較
    if new_close != status[ticker]["last_close"]:
        status[ticker]["updated"] = True
        status[ticker]["last_update_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        status[ticker]["last_close"] = new_close
        updated = True
    else:
        status[ticker]["updated"] = False

# JSON に保存
with open("update_status.json", "w") as f:
    json.dump(status, f, indent=4)

print("終値更新チェック完了")
