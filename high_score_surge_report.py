# high_score_surge_report.py

"""高スコア銘柄の20取引日以内の上昇実績を集計する。"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

from analysis_engine import prepare_dataframe
from scoring import calc_rebound_score
from tickers import TICKERS


PROJECT_ROOT = Path(__file__).resolve().parent
REPORT_PATH = PROJECT_ROOT / "reports" / "high_score_surge_summary.json"
DEFAULT_PERIOD = "5y"
DEFAULT_LOOKAHEAD_DAYS = 20
HIGH_SCORE_THRESHOLD = 60
TARGET_RETURN_PCT = 2.0
SURGE_RETURN_PCT = 5.0


def classify_rsi_band(rsi: float) -> str:
    """RSIを比較用の4区分に分類する。"""
    if rsi <= 30:
        return "RSI30以下"
    if rsi <= 40:
        return "RSI31-40"
    if rsi <= 50:
        return "RSI41-50"
    return "RSI51超"


def parse_arguments() -> argparse.Namespace:
    """コマンドライン引数を取得する。"""
    parser = argparse.ArgumentParser(
        description="高スコア銘柄の上昇実績を検証します。"
    )
    parser.add_argument("--period", default=DEFAULT_PERIOD)
    parser.add_argument(
        "--lookahead-days",
        type=int,
        default=DEFAULT_LOOKAHEAD_DAYS,
    )
    return parser.parse_args()


def create_records(
    price_data: pd.DataFrame,
    lookahead_days: int,
) -> tuple[pd.DataFrame, list[str]]:
    """60点以上となった日ごとの将来上昇実績を作成する。"""
    records = []
    skipped_tickers = []

    for ticker, name in TICKERS.items():
        try:
            ticker_data = price_data[ticker].dropna(how="all")
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

            close = float(row["Close"])
            previous_close = float(data["Close"].iloc[index - 1])
            score = calc_rebound_score(
                is_25ma_touch=bool(row["25MAタッチ"]),
                is_box_bottom_touch=bool(row["20日安値タッチ"]),
                rsi=float(row["RSI"]),
                macd=float(row["MACD"]),
                signal=float(row["Signal"]),
                close_today=close,
                close_yesterday=previous_close,
            )
            if score < HIGH_SCORE_THRESHOLD:
                continue

            future_close = data["Close"].iloc[
                index + 1:index + 1 + lookahead_days
            ]
            max_future_close = float(future_close.max())
            max_return_pct = (max_future_close / close - 1) * 100
            reached_2pct = future_close[
                future_close >= close * (1 + TARGET_RETURN_PCT / 100)
            ]
            days_to_2pct = (
                int((reached_2pct.index[0] - data.index[index]).days)
                if not reached_2pct.empty
                else None
            )

            condition_fields = {
                "\u0032\u0035MA\u30bf\u30c3\u30c1": bool(
                    row["\u0032\u0035MA\u30bf\u30c3\u30c1"]
                ),
                "\u0032\u0030\u65e5\u5b89\u5024\u30bf\u30c3\u30c1": bool(
                    row["\u0032\u0030\u65e5\u5b89\u5024\u30bf\u30c3\u30c1"]
                ),
                "RSI\u5e2f": classify_rsi_band(float(row["RSI"])),
                "MACD\u6761\u4ef6": (
                    "MACD\u30b4\u30fc\u30eb\u30c7\u30f3\u30af\u30ed\u30b9"
                    if float(row["MACD"]) >= float(row["Signal"])
                    else "MACD\u30c7\u30c3\u30c9\u30af\u30ed\u30b9"
                ),
            }

            records.append(
                {
                    **condition_fields,
                    "銘柄コード": ticker,
                    "銘柄名": name,
                    "判定日": pd.Timestamp(
                        data.index[index]
                    ).strftime("%Y-%m-%d"),
                    "反発確度スコア": score,
                    "反発初動": bool(row["反発初動"]),
                    "RSI": round(float(row["RSI"]), 2),
                    "MACD": round(float(row["MACD"]), 3),
                    "Signal": round(float(row["Signal"]), 3),
                    "最大上昇率(%)": round(max_return_pct, 3),
                    "2%到達": not reached_2pct.empty,
                    "2%到達日数": days_to_2pct,
                    "5%以上上昇": max_return_pct >= SURGE_RETURN_PCT,
                }
            )

    return pd.DataFrame(records), skipped_tickers


def summarize_condition(group: pd.DataFrame, condition_name: str) -> dict:
    """指定条件の高スコア銘柄における上昇実績を集計する。"""
    if group.empty:
        return {
            "条件": condition_name,
            "高スコア件数": 0,
            "2%到達率(%)": None,
            "5%以上上昇率(%)": None,
            "平均最大上昇率(%)": None,
        }

    return {
        "条件": condition_name,
        "高スコア件数": int(len(group)),
        "2%到達率(%)": round(float(group["2%到達"].mean() * 100), 2),
        "5%以上上昇率(%)": round(
            float(group["5%以上上昇"].mean() * 100),
            2,
        ),
        "平均最大上昇率(%)": round(
            float(group["最大上昇率(%)"].mean()),
            3,
        ),
    }


def summarize_tickers(records: pd.DataFrame) -> list[dict]:
    """銘柄ごとの高スコア時の上昇実績を集計する。"""
    summaries = []

    for ticker, group in records.groupby("銘柄コード", sort=True):
        summaries.append(
            {
                "銘柄コード": ticker,
                "銘柄名": group["銘柄名"].iloc[0],
                "高スコア件数": int(len(group)),
                "平均スコア": round(
                    float(group["反発確度スコア"].mean()),
                    2,
                ),
                "2%到達率(%)": round(
                    float(group["2%到達"].mean() * 100),
                    2,
                ),
                "5%以上上昇率(%)": round(
                    float(group["5%以上上昇"].mean() * 100),
                    2,
                ),
                "平均最大上昇率(%)": round(
                    float(group["最大上昇率(%)"].mean()),
                    3,
                ),
            }
        )

    return sorted(
        summaries,
        key=lambda item: (
            item["5%以上上昇率(%)"],
            item["平均最大上昇率(%)"],
        ),
        reverse=True,
    )


def summarize_groups(records: pd.DataFrame, column: str) -> list[dict]:
    """指定した条件列ごとに高騰実績を集計する。"""
    summaries = []
    for condition_name, group in records.groupby(column, sort=False):
        summaries.append(summarize_condition(group, str(condition_name)))

    return sorted(
        summaries,
        key=lambda item: (
            item["\u0035%\u4ee5\u4e0a\u4e0a\u6607\u7387(%)"]
            if item["\u0035%\u4ee5\u4e0a\u4e0a\u6607\u7387(%)"] is not None
            else -1,
            item["\u9ad8\u30b9\u30b3\u30a2\u4ef6\u6570"],
        ),
        reverse=True,
    )


def create_combination_summary(
    records: pd.DataFrame,
    condition_name: str,
    condition: pd.Series,
) -> dict:
    """複数条件の組み合わせを1行で集計する。"""
    return summarize_condition(records[condition], condition_name)


def create_condition_summaries(records: pd.DataFrame) -> dict:
    """スコア改善の判断材料となる条件別・組み合わせ別集計を作成する。"""
    macd_golden = (
        records["MACD\u6761\u4ef6"]
        == "MACD\u30b4\u30fc\u30eb\u30c7\u30f3\u30af\u30ed\u30b9"
    )
    low20_touch = records["\u0032\u0030\u65e5\u5b89\u5024\u30bf\u30c3\u30c1"]
    ma25_touch = records["\u0032\u0035MA\u30bf\u30c3\u30c1"]
    rsi_40_or_lower = records["RSI"] <= 40

    combinations = [
        create_combination_summary(
            records,
            "20\u65e5\u5b89\u5024\u30bf\u30c3\u30c1 \u304b\u3064 MACD\u30b4\u30fc\u30eb\u30c7\u30f3\u30af\u30ed\u30b9",
            low20_touch & macd_golden,
        ),
        create_combination_summary(
            records,
            "20\u65e5\u5b89\u5024\u30bf\u30c3\u30c1 \u304b\u3064 MACD\u30c7\u30c3\u30c9\u30af\u30ed\u30b9",
            low20_touch & ~macd_golden,
        ),
        create_combination_summary(
            records,
            "25MA\u30bf\u30c3\u30c1 \u304b\u3064 MACD\u30b4\u30fc\u30eb\u30c7\u30f3\u30af\u30ed\u30b9",
            ma25_touch & macd_golden,
        ),
        create_combination_summary(
            records,
            "25MA\u30bf\u30c3\u30c1 \u304b\u3064 MACD\u30c7\u30c3\u30c9\u30af\u30ed\u30b9",
            ma25_touch & ~macd_golden,
        ),
        create_combination_summary(
            records,
            "RSI40\u4ee5\u4e0b \u304b\u3064 MACD\u30b4\u30fc\u30eb\u30c7\u30f3\u30af\u30ed\u30b9",
            rsi_40_or_lower & macd_golden,
        ),
        create_combination_summary(
            records,
            "RSI40\u4ee5\u4e0b \u304b\u3064 MACD\u30c7\u30c3\u30c9\u30af\u30ed\u30b9",
            rsi_40_or_lower & ~macd_golden,
        ),
    ]

    return {
        "25MA\u6761\u4ef6": summarize_groups(
            records,
            "\u0032\u0035MA\u30bf\u30c3\u30c1",
        ),
        "20\u65e5\u5b89\u5024\u6761\u4ef6": summarize_groups(
            records,
            "\u0032\u0030\u65e5\u5b89\u5024\u30bf\u30c3\u30c1",
        ),
        "RSI\u6761\u4ef6": summarize_groups(records, "RSI\u5e2f"),
        "MACD\u6761\u4ef6": summarize_groups(records, "MACD\u6761\u4ef6"),
        "\u7d44\u307f\u5408\u308f\u305b\u6761\u4ef6": sorted(
            combinations,
            key=lambda item: (
                item["\u0035%\u4ee5\u4e0a\u4e0a\u6607\u7387(%)"]
                if item["\u0035%\u4ee5\u4e0a\u4e0a\u6607\u7387(%)"] is not None
                else -1,
                item["\u9ad8\u30b9\u30b3\u30a2\u4ef6\u6570"],
            ),
            reverse=True,
        ),
    }


def create_time_split_condition_summaries(records: pd.DataFrame) -> dict:
    """条件別の高騰実績を時系列で前半70%・後半30%に分けて検証する。"""
    analyzed_dates = pd.to_datetime(records["\u5224\u5b9a\u65e5"])
    split_index = max(0, int(len(records) * 0.7) - 1)
    split_date = analyzed_dates.sort_values().iloc[split_index]
    early_period = analyzed_dates <= split_date
    later_period = analyzed_dates > split_date
    macd_golden = (
        records["MACD\u6761\u4ef6"]
        == "MACD\u30b4\u30fc\u30eb\u30c7\u30f3\u30af\u30ed\u30b9"
    )
    low20_touch = records["\u0032\u0030\u65e5\u5b89\u5024\u30bf\u30c3\u30c1"]
    rsi_41_to_50 = records["RSI\u5e2f"] == "RSI41-50"
    rsi_40_or_lower = records["RSI"] <= 40

    conditions = [
        ("\u30b9\u30b3\u30a260\u70b9\u4ee5\u4e0a\uff08\u5168\u4f53\uff09", pd.Series(True, index=records.index)),
        (
            "20\u65e5\u5b89\u5024\u30bf\u30c3\u30c1 \u304b\u3064 MACD\u30b4\u30fc\u30eb\u30c7\u30f3\u30af\u30ed\u30b9",
            low20_touch & macd_golden,
        ),
        ("RSI41-50", rsi_41_to_50),
        ("MACD\u30b4\u30fc\u30eb\u30c7\u30f3\u30af\u30ed\u30b9", macd_golden),
        (
            "RSI40\u4ee5\u4e0b \u304b\u3064 MACD\u30c7\u30c3\u30c9\u30af\u30ed\u30b9",
            rsi_40_or_lower & ~macd_golden,
        ),
    ]
    summaries = []
    for condition_name, condition in conditions:
        for period_name, period_filter in [
            ("\u524d\u534a70%", early_period),
            ("\u5f8c\u534a30%", later_period),
        ]:
            summary = summarize_condition(
                records[condition & period_filter],
                condition_name,
            )
            summary["\u691c\u8a3c\u671f\u9593"] = period_name
            summaries.append(summary)

    return {
        "\u5206\u5272\u65e5": split_date.strftime("%Y-%m-%d"),
        "\u96c6\u8a08": summaries,
    }


def create_summary(
    records: pd.DataFrame,
    skipped_tickers: list[str],
    period: str,
    lookahead_days: int,
) -> dict:
    """画面表示用の高スコア高騰レポートを作成する。"""
    reached_2pct_rate = (
        float(records["2%到達"].mean() * 100)
        if not records.empty
        else None
    )
    surged_rate = (
        float(records["5%以上上昇"].mean() * 100)
        if not records.empty
        else None
    )
    top_examples = records.sort_values(
        "最大上昇率(%)",
        ascending=False,
    ).head(30)
    initial_rebounds = records[records["反発初動"]]
    non_initial_rebounds = records[~records["反発初動"]]

    return {
        "score_improvement_condition_summary": create_condition_summaries(
            records
        ),
        "score_improvement_time_split_summary": (
            create_time_split_condition_summaries(records)
        ),
        "作成日時UTC": datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "検証条件": {
            "取得期間": period,
            "確認期間(取引日)": lookahead_days,
            "高スコア閾値": HIGH_SCORE_THRESHOLD,
            "2%到達基準(%)": TARGET_RETURN_PCT,
            "高騰基準(最大終値上昇率%)": SURGE_RETURN_PCT,
            "注意事項": (
                "終値ベースの過去検証であり、"
                "将来の上昇を保証しません。"
            ),
        },
        "全体集計": {
            "高スコア件数": int(len(records)),
            "2%到達率(%)": round(reached_2pct_rate, 2)
            if reached_2pct_rate is not None
            else None,
            "5%以上上昇率(%)": round(surged_rate, 2)
            if surged_rate is not None
            else None,
            "平均最大上昇率(%)": round(
                float(records["最大上昇率(%)"].mean()),
                3,
            )
            if not records.empty
            else None,
            "対象銘柄数": int(records["銘柄コード"].nunique())
            if not records.empty
            else 0,
            "除外銘柄数": len(skipped_tickers),
        },
        "銘柄別集計": summarize_tickers(records),
        "条件別集計": [
            summarize_condition(records, "スコア60点以上（全体）"),
            summarize_condition(
                initial_rebounds,
                "スコア60点以上 かつ 反発初動",
            ),
            summarize_condition(
                non_initial_rebounds,
                "スコア60点以上 かつ 反発初動ではない",
            ),
        ],
        "高騰事例上位": top_examples.to_dict(orient="records"),
    }


def main() -> None:
    """価格取得から集計JSONの保存までを実行する。"""
    arguments = parse_arguments()

    if arguments.lookahead_days <= 0:
        raise ValueError(
            "--lookahead-days は1以上を指定してください。"
        )

    prices = yf.download(
        list(TICKERS.keys()),
        period=arguments.period,
        group_by="ticker",
        threads=True,
        auto_adjust=True,
        progress=False,
    )

    records, skipped_tickers = create_records(
        prices,
        arguments.lookahead_days,
    )

    if records.empty:
        raise RuntimeError(
            "高スコアの検証対象データを作成できませんでした。"
        )

    summary = create_summary(
        records=records,
        skipped_tickers=skipped_tickers,
        period=arguments.period,
        lookahead_days=arguments.lookahead_days,
    )

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with REPORT_PATH.open("w", encoding="utf-8") as file:
        json.dump(summary, file, ensure_ascii=False, indent=2)
        file.write("\n")

    overall = summary["全体集計"]
    print(f"高スコア高騰レポートを保存しました: {REPORT_PATH}")
    print(
        "高スコア件数: {count}, 5%以上上昇率: {rate}%".format(
            count=overall["高スコア件数"],
            rate=overall["5%以上上昇率(%)"],
        )
    )
    for condition in summary["条件別集計"]:
        print(
            "{name}: 件数 {count}, 5%以上上昇率 {rate}%, 平均最大上昇率 {maximum}%".format(
                name=condition["条件"],
                count=condition["高スコア件数"],
                rate=condition["5%以上上昇率(%)"],
                maximum=condition["平均最大上昇率(%)"],
            )
        )


    print("\nスコア改善用の条件別実績（5%以上上昇率順）")
    for category, conditions in summary[
        "score_improvement_condition_summary"
    ].items():
        print(f"[{category}]")
        for condition in conditions:
            print(
                "{name}: 件数 {count}, 5%以上上昇率 {rate}%, "
                "平均最大上昇率 {maximum}%".format(
                    name=condition["\u6761\u4ef6"],
                    count=condition["\u9ad8\u30b9\u30b3\u30a2\u4ef6\u6570"],
                    rate=condition["\u0035%\u4ee5\u4e0a\u4e0a\u6607\u7387(%)"],
                    maximum=condition["\u5e73\u5747\u6700\u5927\u4e0a\u6607\u7387(%)"],
                )
            )

    time_split_summary = summary["score_improvement_time_split_summary"]
    print(
        "\n時系列分割による条件別再現性（分割日: {date}）".format(
            date=time_split_summary["\u5206\u5272\u65e5"]
        )
    )
    for condition in time_split_summary["\u96c6\u8a08"]:
        print(
            "{name} / {period}: 件数 {count}, 5%以上上昇率 {rate}%, "
            "平均最大上昇率 {maximum}%".format(
                name=condition["\u6761\u4ef6"],
                period=condition["\u691c\u8a3c\u671f\u9593"],
                count=condition["\u9ad8\u30b9\u30b3\u30a2\u4ef6\u6570"],
                rate=condition["\u0035%\u4ee5\u4e0a\u4e0a\u6607\u7387(%)"],
                maximum=condition["\u5e73\u5747\u6700\u5927\u4e0a\u6607\u7387(%)"],
            )
        )


if __name__ == "__main__":
    main()
