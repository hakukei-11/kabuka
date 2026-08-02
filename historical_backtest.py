# historical_backtest.py

"""yfinanceの過去日足を使い、反発確度スコアの2%到達率を検証する。"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

from analysis_engine import THRESHOLD, prepare_dataframe
from scoring import calc_rebound_score
from tickers import TICKERS


PROJECT_ROOT = Path(__file__).resolve().parent
REPORT_PATH = PROJECT_ROOT / "reports" / "historical_backtest_summary.json"


def parse_arguments() -> argparse.Namespace:
    """コマンドライン引数を取得する。"""
    parser = argparse.ArgumentParser(description="過去日足で2%到達率を検証します。")
    parser.add_argument("--period", default="2y", help="取得期間（初期値: 2y）")
    parser.add_argument("--lookahead-days", type=int, default=20, help="確認取引日数（初期値: 20）")
    parser.add_argument("--target-return-pct", type=float, default=2.0, help="目標上昇率（初期値: 2.0%%）")
    return parser.parse_args()


def get_score_band(score: int) -> str:
    """スコアを集計用の帯に変換する。"""
    if score >= 80:
        return "80点以上"
    if score >= 60:
        return "60-79点"
    if score >= 50:
        return "50-59点"
    return "0-49点"


def get_rsi_band(rsi: float) -> str:
    """RSIを現行スコアの閾値に合わせた帯へ変換する。"""
    if rsi <= 25:
        return "RSI 25以下"
    if rsi <= 30:
        return "RSI 26-30"
    if rsi <= 40:
        return "RSI 31-40"
    return "RSI 41超"


def download_price_data(period: str) -> pd.DataFrame:
    """対象銘柄の調整済み日足を一括取得する。"""
    return yf.download(
        list(TICKERS.keys()),
        period=period,
        group_by="ticker",
        threads=True,
        auto_adjust=True,
        progress=False,
    )


def create_records(
    downloaded_data: pd.DataFrame,
    lookahead_days: int,
    target_return_pct: float,
) -> tuple[pd.DataFrame, list[str]]:
    """全銘柄・全取引日のスコアと2%到達結果を作る。"""
    records = []
    skipped_tickers = []
    target_multiplier = 1 + target_return_pct / 100

    for ticker, name in TICKERS.items():
        try:
            price_data = downloaded_data[ticker].dropna(how="all")
        except (KeyError, TypeError):
            skipped_tickers.append(ticker)
            continue

        analyzed_data = prepare_dataframe(price_data)
        if analyzed_data is None or len(analyzed_data) <= lookahead_days:
            skipped_tickers.append(ticker)
            continue

        for index in range(len(analyzed_data) - lookahead_days):
            row = analyzed_data.iloc[index]
            previous_close = float(analyzed_data["Close"].iloc[index - 1])
            close = float(row["Close"])
            ma25 = float(row["25MA"])
            high20 = float(row["High20"])
            low20 = float(row["Low20"])
            rsi = float(row["RSI"])
            macd = float(row["MACD"])
            signal = float(row["Signal"])

            if any(pd.isna(value) for value in [ma25, high20, low20, rsi, macd, signal]):
                continue

            deviation_ma = ((close - ma25) / ma25) * 100
            is_25ma_touch = abs(deviation_ma) <= THRESHOLD
            is_box_bottom_touch = abs(close - low20) <= low20 * THRESHOLD / 100

            score = calc_rebound_score(
                is_25ma_touch=is_25ma_touch,
                is_box_bottom_touch=is_box_bottom_touch,
                rsi=rsi,
                macd=macd,
                signal=signal,
                close_today=close,
                close_yesterday=previous_close,
            )

            future_close = analyzed_data["Close"].iloc[index + 1 : index + 1 + lookahead_days]
            target_price = close * target_multiplier
            reached = future_close[future_close >= target_price]

            if reached.empty:
                result = "未到達"
                days_to_target = None
            else:
                result = "成功"
                days_to_target = int(
                    (reached.index[0] - analyzed_data.index[index]).days
                )

            records.append(
                {
                    "銘柄コード": ticker,
                    "銘柄名": name,
                    "取引日": pd.Timestamp(analyzed_data.index[index]).strftime("%Y-%m-%d"),
                    "反発確度スコア": score,
                    "スコア帯": get_score_band(score),
                    "25MA条件": "25MAタッチ" if is_25ma_touch else "25MA非タッチ",
                    "20日安値条件": (
                        "20日安値タッチ"
                        if is_box_bottom_touch
                        else "20日安値非タッチ"
                    ),
                    "RSI条件": get_rsi_band(rsi),
                    "MACD条件": (
                        "MACDがシグナル超え"
                        if macd > signal
                        else "MACDがシグナル以下"
                    ),
                    "結果": result,
                    "到達日数": days_to_target,
                }
            )

    return pd.DataFrame(records), skipped_tickers


def summarize(records: pd.DataFrame, group_column: str) -> list[dict]:
    """指定列ごとの成功率と平均到達日数を集計する。"""
    summaries = []
    for group_value, group in records.groupby(group_column, sort=True):
        success = group[group["結果"] == "成功"]
        success_rate = (len(success) / len(group)) * 100
        average_days = success["到達日数"].mean() if not success.empty else None
        summaries.append(
            {
                group_column: str(group_value),
                "検証件数": int(len(group)),
                "成功件数": int(len(success)),
                "未到達件数": int(len(group) - len(success)),
                "成功率(%)": round(success_rate, 2),
                "平均到達日数": round(float(average_days), 2)
                if average_days is not None
                else None,
            }
        )
    return summaries


def create_summary(
    records: pd.DataFrame,
    skipped_tickers: list[str],
    period: str,
    lookahead_days: int,
    target_return_pct: float,
) -> dict:
    """Streamlit用の履歴バックテスト集計JSONを作成する。"""
    success = records[records["結果"] == "成功"]
    success_rate = (len(success) / len(records)) * 100 if not records.empty else None

    return {
        "作成日時UTC": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "検証条件": {
            "取得期間": period,
            "目標上昇率(%)": target_return_pct,
            "確認期間(取引日)": lookahead_days,
            "価格条件": "調整済み終値が、判定時終値の目標上昇率以上に到達",
            "注意事項": "過去の価格データによる検証であり、将来の成果を保証しません。",
        },
        "全体集計": {
            "検証件数": int(len(records)),
            "成功件数": int(len(success)),
            "未到達件数": int(len(records) - len(success)),
            "成功率(%)": round(success_rate, 2) if success_rate is not None else None,
            "対象銘柄数": int(records["銘柄コード"].nunique()) if not records.empty else 0,
            "除外銘柄数": len(skipped_tickers),
        },
        "スコア別集計": summarize(records, "スコア帯"),
        "条件別集計": {
            "25MA条件": summarize(records, "25MA条件"),
            "20日安値条件": summarize(records, "20日安値条件"),
            "RSI条件": summarize(records, "RSI条件"),
            "MACD条件": summarize(records, "MACD条件"),
        },
        "銘柄別集計": summarize(records, "銘柄コード"),
    }


def write_summary(summary: dict) -> None:
    """集計結果をJSONへ保存する。"""
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with REPORT_PATH.open("w", encoding="utf-8") as file:
        json.dump(summary, file, ensure_ascii=False, indent=2)
        file.write("\n")


def main() -> None:
    """履歴データの取得、検証、レポート出力を実行する。"""
    arguments = parse_arguments()
    if arguments.lookahead_days <= 0 or arguments.target_return_pct <= 0:
        raise ValueError("確認取引日数と目標上昇率は0より大きい値を指定してください。")

    downloaded_data = download_price_data(arguments.period)
    records, skipped_tickers = create_records(
        downloaded_data=downloaded_data,
        lookahead_days=arguments.lookahead_days,
        target_return_pct=arguments.target_return_pct,
    )
    if records.empty:
        raise RuntimeError("履歴バックテストの対象データを作成できませんでした。")

    summary = create_summary(
        records=records,
        skipped_tickers=skipped_tickers,
        period=arguments.period,
        lookahead_days=arguments.lookahead_days,
        target_return_pct=arguments.target_return_pct,
    )
    write_summary(summary)
    overall = summary["全体集計"]
    print(f"履歴バックテスト結果を保存しました: {REPORT_PATH}")
    print(f"検証件数: {overall['検証件数']}, 成功率: {overall['成功率(%)']}%")


if __name__ == "__main__":
    main()
