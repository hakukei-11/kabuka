# score_risk_report.py

"""反発確度スコア別に、利確・損失ラインの先後を検証する。"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

from analysis_engine import prepare_dataframe
from risk_backtest import get_first_event
from scoring import calc_rebound_score
from tickers import TICKERS


PROJECT_ROOT = Path(__file__).resolve().parent
REPORT_PATH = PROJECT_ROOT / "reports" / "score_risk_summary.json"
DEFAULT_PERIOD = "5y"
LOOKAHEAD_DAYS = 20
TARGET_RETURN_PCT = 2.0
STOP_LOSS_PCTS = (3.0, 5.0)


def parse_arguments() -> argparse.Namespace:
    """コマンドライン引数を取得する。"""
    parser = argparse.ArgumentParser(
        description="反発確度スコア別の利確・損失ライン到達率を検証します。"
    )
    parser.add_argument("--period", default=DEFAULT_PERIOD)
    parser.add_argument(
        "--lookahead-days",
        type=int,
        default=LOOKAHEAD_DAYS,
    )
    return parser.parse_args()


def get_score_band(score: int) -> str:
    """表示用のスコア帯を返す。"""
    if score < 50:
        return "0-49点"
    if score < 60:
        return "50-59点"
    if score < 70:
        return "60-69点"
    if score < 80:
        return "70-79点"
    return "80点以上"


def create_records(
    prices: pd.DataFrame,
    lookahead_days: int,
) -> tuple[pd.DataFrame, list[str]]:
    """全銘柄・全取引日のスコアと利確・損失イベントを作成する。"""
    records = []
    skipped_tickers = []

    for ticker, name in TICKERS.items():
        try:
            ticker_data = prices[ticker].dropna(how="all")
        except (KeyError, TypeError):
            skipped_tickers.append(ticker)
            continue

        data = prepare_dataframe(ticker_data)
        if data is None or len(data) <= lookahead_days:
            skipped_tickers.append(ticker)
            continue

        for index in range(1, len(data) - lookahead_days):
            row = data.iloc[index]
            required_values = [
                row["RSI"],
                row["MACD"],
                row["Signal"],
                row["25MA"],
                row["Low20"],
            ]
            if any(pd.isna(value) for value in required_values):
                continue

            entry_price = float(row["Close"])
            previous_close = float(data["Close"].iloc[index - 1])
            score = calc_rebound_score(
                is_25ma_touch=bool(row["25MAタッチ"]),
                is_box_bottom_touch=bool(row["20日安値タッチ"]),
                rsi=float(row["RSI"]),
                macd=float(row["MACD"]),
                signal=float(row["Signal"]),
                close_today=entry_price,
                close_yesterday=previous_close,
            )
            future = data.iloc[index + 1:index + 1 + lookahead_days]
            record = {
                "銘柄コード": ticker,
                "銘柄名": name,
                "判定日": pd.Timestamp(data.index[index]).strftime("%Y-%m-%d"),
                "反発確度スコア": score,
                "スコア帯": get_score_band(score),
            }

            for stop_loss_pct in STOP_LOSS_PCTS:
                event_column = f"+2%対-{int(stop_loss_pct)}%"
                record[event_column] = get_first_event(
                    future=future,
                    target_price=entry_price * (1 + TARGET_RETURN_PCT / 100),
                    stop_price=entry_price * (1 - stop_loss_pct / 100),
                )

            records.append(record)

    return pd.DataFrame(records), skipped_tickers


def summarize_group(
    group: pd.DataFrame,
    group_name: str,
    stop_loss_pct: float,
) -> dict:
    """スコアまたはスコア帯ごとの利確・損失ライン先後を集計する。"""
    event_column = f"+2%対-{int(stop_loss_pct)}%"
    total = len(group)
    target_first = int((group[event_column] == "利確先行").sum())
    stop_first = int((group[event_column] == "損失先行").sum())
    same_day = int((group[event_column] == "同日両方").sum())
    no_event = int((group[event_column] == "未到達").sum())

    return {
        "スコア": group_name,
        "損失ライン": f"-{int(stop_loss_pct)}%",
        "検証件数": total,
        "利確先行件数": target_first,
        "損失先行件数": stop_first,
        "同日両方件数": same_day,
        "未到達件数": no_event,
        "保守的成功率(%)": round(target_first / total * 100, 2),
        "楽観的成功率(%)": round(
            (target_first + same_day) / total * 100,
            2,
        ),
        "損失先行率(%)": round(stop_first / total * 100, 2),
    }


def summarize_by_column(
    records: pd.DataFrame,
    column: str,
    stop_loss_pct: float,
) -> list[dict]:
    """指定列ごとの利確・損失ライン先後を集計する。"""
    summaries = [
        summarize_group(group, str(value), stop_loss_pct)
        for value, group in records.groupby(column, sort=True)
    ]

    if column == "反発確度スコア":
        return sorted(summaries, key=lambda item: int(item["スコア"]))

    order = {"0-49点": 0, "50-59点": 1, "60-69点": 2, "70-79点": 3, "80点以上": 4}
    return sorted(summaries, key=lambda item: order[item["スコア"]])


def summarize_time_split(
    records: pd.DataFrame,
    stop_loss_pct: float,
) -> dict:
    """スコア帯別の成績を前半70%・後半30%で比較する。"""
    trade_dates = sorted(records["判定日"].unique().tolist())
    split_index = max(0, int(len(trade_dates) * 0.7) - 1)
    split_date = trade_dates[split_index]
    summaries = []

    for period_name, period_records in [
        ("前半70%", records[records["判定日"] <= split_date]),
        ("後半30%", records[records["判定日"] > split_date]),
    ]:
        for score_band, group in period_records.groupby("スコア帯", sort=True):
            summary = summarize_group(group, str(score_band), stop_loss_pct)
            summary["検証期間"] = period_name
            summaries.append(summary)

    order = {"0-49点": 0, "50-59点": 1, "60-69点": 2, "70-79点": 3, "80点以上": 4}
    summaries.sort(key=lambda item: (order[item["スコア"]], item["検証期間"]))
    return {"分割日": split_date, "集計": summaries}


def create_summary(
    records: pd.DataFrame,
    skipped_tickers: list[str],
    period: str,
    lookahead_days: int,
) -> dict:
    """画面表示・保存用の集計JSONを作成する。"""
    score_summaries = {}
    score_band_summaries = {}
    time_split_summaries = {}

    for stop_loss_pct in STOP_LOSS_PCTS:
        stop_label = f"-{int(stop_loss_pct)}%"
        score_summaries[stop_label] = summarize_by_column(
            records,
            "反発確度スコア",
            stop_loss_pct,
        )
        score_band_summaries[stop_label] = summarize_by_column(
            records,
            "スコア帯",
            stop_loss_pct,
        )
        time_split_summaries[stop_label] = summarize_time_split(
            records,
            stop_loss_pct,
        )

    return {
        "作成日時UTC": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "検証条件": {
            "取得期間": period,
            "確認期間(営業日)": lookahead_days,
            "利確目標(%)": TARGET_RETURN_PCT,
            "損失ライン(%)": list(STOP_LOSS_PCTS),
            "注意事項": (
                "同日に利確価格と損失価格の両方へ到達した順序は日足だけでは判定できません。"
                "保守的成功率では失敗、楽観的成功率では成功として扱います。"
            ),
        },
        "全検証件数": int(len(records)),
        "除外銘柄数": len(skipped_tickers),
        "点数別集計": score_summaries,
        "点数帯別集計": score_band_summaries,
        "時系列分割集計": time_split_summaries,
    }


def print_summary(summary: dict) -> None:
    """ターミナルで確認しやすい形に結果を表示する。"""
    print(f"スコア別リスク検証レポートを保存しました: {REPORT_PATH}")
    print(f"全検証件数: {summary['全検証件数']}")

    for stop_label, rows in summary["点数帯別集計"].items():
        print(f"\n【利確+2% / 損失ライン{stop_label}】")
        for row in rows:
            print(
                "{score}: 件数 {count}, 保守的成功率 {conservative}%, "
                "楽観的成功率 {optimistic}%, 損失先行率 {stop_rate}%".format(
                    score=row["スコア"],
                    count=row["検証件数"],
                    conservative=row["保守的成功率(%)"],
                    optimistic=row["楽観的成功率(%)"],
                    stop_rate=row["損失先行率(%)"],
                )
            )


def main() -> None:
    """価格取得から集計JSON保存までを実行する。"""
    arguments = parse_arguments()
    if arguments.lookahead_days <= 0:
        raise ValueError("--lookahead-days は1以上を指定してください。")

    prices = yf.download(
        list(TICKERS.keys()),
        period=arguments.period,
        group_by="ticker",
        threads=True,
        auto_adjust=True,
        progress=False,
    )
    records, skipped_tickers = create_records(prices, arguments.lookahead_days)
    if records.empty:
        raise RuntimeError("スコア別リスク検証用のデータを作成できませんでした。")

    summary = create_summary(
        records,
        skipped_tickers,
        arguments.period,
        arguments.lookahead_days,
    )
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with REPORT_PATH.open("w", encoding="utf-8") as file:
        json.dump(summary, file, ensure_ascii=False, indent=2)
        file.write("\n")

    print_summary(summary)


if __name__ == "__main__":
    main()
