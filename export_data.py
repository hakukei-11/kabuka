# export_data.py

import os

import pandas as pd
import requests

from analysis_engine import analyze_ticker, get_analysis_executed_at
from tickers import TICKERS

LINE_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_URL = "https://api.line.me/v2/bot/message/push"
USER_ID = "U889b3c025bd9a29b4651833d39a4f7a6"


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


def main():
    """全銘柄を分析し、日次CSVを保存する。"""
    analysis_executed_at = get_analysis_executed_at()
    results = []

    for ticker, name in TICKERS.items():
        result, _ = analyze_ticker(
            ticker=ticker,
            name=name,
            analysis_executed_at=analysis_executed_at,
        )

        if result is not None:
            results.append(result)

    if not results:
        raise RuntimeError("保存対象となる分析結果がありません。")

    result_df = pd.DataFrame(results)

    execution_date = analysis_executed_at[:10]
    year, month, day = execution_date.split("-")

    folder_path = f"data/{year}/{month}"
    file_path = f"{folder_path}/data_{year}{month}{day}.csv"

    os.makedirs(folder_path, exist_ok=True)

    columns = [
        "分析実行日時",
        "取引日",
        "銘柄コード",
        "銘柄名",
        "終値",
        "前日比",
        "前日比率(%)",
        "RSI",
        "MACD",
        "Signal",
        "25MA",
        "20日高値",
        "20日安値",
        "25MAタッチ",
        "20日安値タッチ",
        "判定",
        "反発確度スコア",
    ]

    result_df = result_df.reindex(columns=columns)

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
