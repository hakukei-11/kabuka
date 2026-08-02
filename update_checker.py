# update_checker.py
# 200銘柄（日本100＋米国100）対応版

import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from analysis_engine import analyze_ticker
from tickers import TICKERS

LINE_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_URL = "https://api.line.me/v2/bot/message/push"
USER_ID = "U889b3c025bd9a29b4651833d39a4f7a6"

JST = ZoneInfo("Asia/Tokyo")
SCORE_NOTIFICATION_THRESHOLD = 50
CLOSE_CHANGE_THRESHOLD = 0.01
STATUS_FILE_PATH = "update_status.json"


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


def load_status() -> dict:
    """前回の終値更新状態を読み込む。"""
    try:
        with open(STATUS_FILE_PATH, "r", encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        print("update_status.json の形式が不正なため、空の状態から開始します。")
        return {}


def save_status(status: dict):
    """終値更新状態を保存する。"""
    with open(STATUS_FILE_PATH, "w", encoding="utf-8") as file:
        json.dump(
            status,
            file,
            indent=4,
            ensure_ascii=False,
        )


def main():
    """全銘柄の終値更新を確認し、条件を満たす銘柄をLINE通知する。"""
    status = load_status()
    updated_list = []
    checked_at = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")

    for ticker, name in TICKERS.items():
        result, _ = analyze_ticker(ticker=ticker, name=name)

        if result is None:
            continue

        new_close = float(result["終値"])
        trade_date = result["取引日"]
        score = int(result["反発確度スコア"])
        judgment = result["判定"]

        if ticker not in status:
            status[ticker] = {
                "last_close": new_close,
                "last_trade_date": trade_date,
                "updated": False,
                "last_update_time": None,
                "last_checked_at": checked_at,
            }
            continue

        previous_close = float(status[ticker]["last_close"])
        previous_trade_date = status[ticker].get("last_trade_date")

        close_changed = abs(new_close - previous_close) > CLOSE_CHANGE_THRESHOLD
        trade_date_changed = trade_date != previous_trade_date
        is_updated = close_changed or trade_date_changed

        status[ticker]["updated"] = is_updated
        status[ticker]["last_checked_at"] = checked_at

        if not is_updated:
            continue

        status[ticker]["last_close"] = new_close
        status[ticker]["last_trade_date"] = trade_date
        status[ticker]["last_update_time"] = checked_at

        if score >= SCORE_NOTIFICATION_THRESHOLD:
            updated_list.append(
                f"{name}（{ticker}）\n"
                f"取引日：{trade_date}\n"
                f"終値：{new_close}\n"
                f"判定：{judgment}\n"
                f"反発確度スコア：{score}"
            )

    save_status(status)

    if updated_list:
        send_line("\n\n".join(updated_list))
    else:
        print("通知対象の更新銘柄はありません。")


if __name__ == "__main__":
    main()