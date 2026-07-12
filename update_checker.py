# update_checker.py
import yfinance as yf
import json
import requests
import os
from datetime import datetime

# 監視する銘柄リスト（tickers.py に合わせて自由に追加可能）
TICKERS = ["7974.T", "6501.T", "AAPL", "MSFT"]

# GitHub Secrets から読み込む Messaging API トークン
LINE_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")

# LINE Messaging API の Push API エンドポイント
LINE_URL = "https://api.line.me/v2/bot/message/push"

# あなたの LINE ユーザーID（Webhookログで取得した値）
USER_ID = "U889b3c025bd9a29b4651833d39a4f7a6"


def send_line(message: str):
    """LINE Messaging API で通知を送信"""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_TOKEN}"
    }
    data = {
        "to": USER_ID,
        "messages": [
            {"type": "text", "text": message}
        ]
    }
    response = requests.post(LINE_URL, headers=headers, json=data)
    if response.status_code != 200:
        print(f"LINE送信エラー: {response.status_code} - {response.text}")
    else:
        print("LINE送信成功")


def get_close(ticker: str) -> float | None:
    """終値を取得（前日比判定用に2日分）"""
    df = yf.Ticker(ticker).history(period="2d").ffill()
    close = df["Close"].dropna()
    if close.empty:
        print(f"{ticker} の終値データが取得できませんでした。")
        return None
    return float(close.iloc[-1])


# 前回の終値データを読み込み
try:
    with open("update_status.json", "r") as f:
        status = json.load(f)
except FileNotFoundError:
    status = {}

updated_list = []  # 更新された銘柄を記録


for ticker in TICKERS:
    new_close = get_close(ticker)
    if new_close is None:
        continue

    # 初回データがない場合は登録だけする
    if ticker not in status:
        status[ticker] = {
            "last_close": new_close,
            "updated": False,
            "last_update_time": None
        }
        continue

    # 終値が変わったか判定（誤差0.01円以上で更新扱い）
    if abs(new_close - status[ticker]["last_close"]) > 0.01:
        status[ticker]["updated"] = True
        status[ticker]["last_update_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        status[ticker]["last_close"] = new_close
        updated_list.append(f"{ticker} 終値更新 → {new_close}")
    else:
        status[ticker]["updated"] = False


# JSON 保存と例外処理
try:
    with open("update_status.json", "w") as f:
        json.dump(status, f, indent=4, ensure_ascii=False)

    # LINE 通知（更新があった場合のみ）
    if updated_list:
        send_line("\n".join(updated_list))

except Exception as e:
    print(f"エラー発生: {e}")
    exit(0)  # GitHub Actionsを成功扱いで終了
