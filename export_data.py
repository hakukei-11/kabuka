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


def build_validated_candidates_message(
    results: list[dict],
    trade_date: str,
) -> str:
    """20日安値タッチの分析候補をLINE通知用の文面に整形する。"""
    candidates = [
        result for result in results
        if result.get("20日安値タッチ") is True
    ]
    if not candidates:
        return (
            f"取引日: {trade_date}\n"
            "20日安値タッチの分析候補: なし\n"
            "※過去検証に基づく分析条件であり、売買推奨ではありません。"
        )

    initial_rebounds = [
        result for result in candidates
        if result.get("反発初動") is True
    ]
    other_candidates = [
        result for result in candidates
        if result.get("反発初動") is not True
    ]
    lines = [
        f"取引日: {trade_date}",
        f"20日安値タッチの分析候補: {len(candidates)}件",
    ]
    if initial_rebounds:
        lines.append(f"反発初動（優先確認）: {len(initial_rebounds)}件")
    for result in (initial_rebounds + other_candidates)[:10]:
        priority = "【反発初動】" if result.get("反発初動") is True else ""
        lines.append(
            "- {priority}{name}（{ticker}）終値: {close} / RSI: {rsi} / スコア: {score}".format(
                priority=priority,
                name=result["銘柄名"],
                ticker=result["銘柄コード"],
                close=result["終値"],
                rsi=result["RSI"],
                score=result["反発確度スコア"],
            )
        )
    if len(candidates) > 10:
        lines.append(f"ほか {len(candidates) - 10}件")
    lines.append("※過去検証に基づく分析条件であり、売買推奨ではありません。")
    return "\n".join(lines)


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
        "陽線",
        "終値位置(%)",
        "反発初動",
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
        f"分析実行日時: {analysis_executed_at}\n\n"
        + build_validated_candidates_message(
            results=results,
            trade_date=results[0]["取引日"],
        )
    )


if __name__ == "__main__":
    main()
