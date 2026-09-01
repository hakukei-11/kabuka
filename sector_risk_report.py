# sector_risk_report.py

"""業種別に反発確度スコアと検証済み条件の有効性を検証する。"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

from analysis_engine import prepare_dataframe
from risk_backtest import get_first_event
from scoring import calc_rebound_score
from sectors import get_sector
from tickers import TICKERS


PROJECT_ROOT = Path(__file__).resolve().parent
REPORT_PATH = PROJECT_ROOT / "reports" / "sector_risk_summary.json"
DEFAULT_PERIOD = "5y"
LOOKAHEAD_DAYS = 20
TARGET_RETURN_PCT = 2.0
STOP_LOSS_PCTS = (3.0, 5.0)
SCORE_BANDS = (
    (0, 49, "0-49点"),
    (50, 59, "50-59点"),
    (60, 69, "60-69点"),
    (70, 79, "70-79点"),
    (80, None, "80点以上"),
)


def parse_arguments() -> argparse.Namespace:
    """コマンドライン引数を取得する。"""
    parser = argparse.ArgumentParser(
        description="業種別の利確・損失ライン到達順を検証します。"
    )
    parser.add_argument("--period", default=DEFAULT_PERIOD)
    parser.add_argument(
        "--lookahead-days",
        type=int,
        default=LOOKAHEAD_DAYS,
    )
    parser.add_argument(
        "--minimum-samples",
        type=int,
        default=500,
        help="業種・点数帯集計の最小検証件数（初期値: 500）",
    )
    parser.add_argument(
        "--condition-minimum-samples",
        type=int,
        default=30,
        help="検証済み条件集計の最小検証件数（初期値: 30）",
    )
    parser.add_argument(
        "--time-split-minimum-samples",
        type=int,
        default=200,
        help="時系列分割の各期間に必要な最小検証件数（初期値: 200）",
    )
    return parser.parse_args()


def get_score_band(score: int) -> str:
    """表示用の点数帯を返す。"""
    for minimum, maximum, label in SCORE_BANDS:
        if score >= minimum and (maximum is None or score <= maximum):
            return label
    raise ValueError(f"点数帯を判定できません: {score}")


def get_verified_condition(
    row: pd.Series,
    close_today: float,
    close_yesterday: float,
) -> str:
    """過去検証済みの候補条件に該当するかを判定する。"""
    rsi = float(row["RSI"])
    macd = float(row["MACD"])
    signal = float(row["Signal"])
    macd_difference = abs(macd - signal)

    if (
        bool(row["20日安値タッチ"])
        and close_today > close_yesterday
        and rsi <= 25
        and macd <= signal
    ):
        return "優先候補：20日安値・終値上昇・RSI25以下"
    if (
        bool(row["20日安値タッチ"])
        and close_today <= close_yesterday
        and rsi <= 25
        and macd <= signal
        and macd_difference >= 0.1
    ):
        return "逆張り優先候補：20日安値・終値下落等・RSI25以下"
    if (
        bool(row["25MAタッチ"])
        and 30 < rsi <= 40
        and macd > signal
        and macd_difference >= 0.1
    ):
        return "注意候補：25MA・RSI31-40・MACD上向き"
    return "その他"


def create_records(
    prices: pd.DataFrame,
    lookahead_days: int,
) -> tuple[pd.DataFrame, list[str]]:
    """全銘柄・全取引日の業種、点数、利確・損失イベントを記録する。"""
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

            close_today = float(row["Close"])
            close_yesterday = float(data["Close"].iloc[index - 1])
            score = calc_rebound_score(
                is_25ma_touch=bool(row["25MAタッチ"]),
                is_box_bottom_touch=bool(row["20日安値タッチ"]),
                rsi=float(row["RSI"]),
                macd=float(row["MACD"]),
                signal=float(row["Signal"]),
                close_today=close_today,
                close_yesterday=close_yesterday,
            )
            future = data.iloc[index + 1:index + 1 + lookahead_days]
            record = {
                "銘柄コード": ticker,
                "銘柄名": name,
                "業種": get_sector(ticker),
                "取引日": pd.Timestamp(data.index[index]).strftime("%Y-%m-%d"),
                "反発確度スコア": score,
                "スコア帯": get_score_band(score),
                "検証済み条件": get_verified_condition(
                    row,
                    close_today,
                    close_yesterday,
                ),
            }

            for stop_loss_pct in STOP_LOSS_PCTS:
                event_column = f"+2%対-{int(stop_loss_pct)}%"
                record[event_column] = get_first_event(
                    future=future,
                    target_price=close_today * (1 + TARGET_RETURN_PCT / 100),
                    stop_price=close_today * (1 - stop_loss_pct / 100),
                )

            records.append(record)

    return pd.DataFrame(records), skipped_tickers


def summarize_group(
    group: pd.DataFrame,
    stop_loss_pct: float,
) -> dict:
    """利確・損失ライン到達順を集計する。"""
    event_column = f"+2%対-{int(stop_loss_pct)}%"
    total = len(group)
    target_first = int((group[event_column] == "利確先行").sum())
    stop_first = int((group[event_column] == "損失先行").sum())
    same_day = int((group[event_column] == "同日両方").sum())
    no_event = int((group[event_column] == "未到達").sum())

    return {
        "検証件数": total,
        "利確先行件数": target_first,
        "損失先行件数": stop_first,
        "同日両方件数": same_day,
        "未到達件数": no_event,
        "保守的成功率(%)": round(target_first / total * 100, 2),
        "楽観的成功率(%)": round((target_first + same_day) / total * 100, 2),
        "損失先行率(%)": round(stop_first / total * 100, 2),
    }


def summarize_by_columns(
    records: pd.DataFrame,
    columns: list[str],
    stop_loss_pct: float,
    minimum_samples: int,
) -> list[dict]:
    """指定した分類列ごとに、最小件数以上の結果だけを集計する。"""
    rows = []
    for keys, group in records.groupby(columns, sort=True):
        if len(group) < minimum_samples:
            continue
        key_values = keys if isinstance(keys, tuple) else (keys,)
        row = dict(zip(columns, key_values, strict=True))
        row.update(summarize_group(group, stop_loss_pct))
        rows.append(row)
    return sorted(
        rows,
        key=lambda item: (-item["保守的成功率(%)"], -item["検証件数"]),
    )


def summarize_time_split(
    records: pd.DataFrame,
    stop_loss_pct: float,
    minimum_samples: int,
) -> dict:
    """業種・点数帯の成績が前半70%・後半30%で再現するか確認する。"""
    trade_dates = sorted(records["取引日"].unique().tolist())
    split_index = max(0, int(len(trade_dates) * 0.7) - 1)
    split_date = trade_dates[split_index]
    rows = []

    for period_name, period_records in [
        ("前半70%", records[records["取引日"] <= split_date]),
        ("後半30%", records[records["取引日"] > split_date]),
    ]:
        summaries = summarize_by_columns(
            period_records,
            ["業種", "スコア帯"],
            stop_loss_pct,
            minimum_samples,
        )
        for row in summaries:
            row["検証期間"] = period_name
            rows.append(row)

    rows.sort(key=lambda item: (item["業種"], item["スコア帯"], item["検証期間"]))
    return {"分割日": split_date, "集計": rows}


def create_summary(
    records: pd.DataFrame,
    skipped_tickers: list[str],
    period: str,
    lookahead_days: int,
    minimum_samples: int,
    condition_minimum_samples: int,
    time_split_minimum_samples: int,
) -> dict:
    """画面表示・保存用の業種別集計JSONを作成する。"""
    sector_summaries = {}
    sector_score_summaries = {}
    verified_condition_summaries = {}
    time_split_summaries = {}

    condition_records = records[records["検証済み条件"] != "その他"].copy()
    for stop_loss_pct in STOP_LOSS_PCTS:
        stop_label = f"-{int(stop_loss_pct)}%"
        sector_summaries[stop_label] = summarize_by_columns(
            records,
            ["業種"],
            stop_loss_pct,
            minimum_samples,
        )
        sector_score_summaries[stop_label] = summarize_by_columns(
            records,
            ["業種", "スコア帯"],
            stop_loss_pct,
            minimum_samples,
        )
        verified_condition_summaries[stop_label] = summarize_by_columns(
            condition_records,
            ["業種", "検証済み条件"],
            stop_loss_pct,
            condition_minimum_samples,
        )
        time_split_summaries[stop_label] = summarize_time_split(
            records,
            stop_loss_pct,
            time_split_minimum_samples,
        )

    return {
        "作成日時UTC": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "検証条件": {
            "取得期間": period,
            "確認期間(営業日)": lookahead_days,
            "利確目標(%)": TARGET_RETURN_PCT,
            "損失ライン(%)": list(STOP_LOSS_PCTS),
            "業種・点数帯の最小検証件数": minimum_samples,
            "検証済み条件の最小検証件数": condition_minimum_samples,
            "時系列分割の各期間の最小検証件数": time_split_minimum_samples,
            "注意事項": (
                "業種はこのプロジェクトで固定した大分類です。"
                "同日に利確価格と損失価格の両方へ到達した順序は日足だけでは判定できません。"
            ),
        },
        "全検証件数": int(len(records)),
        "除外銘柄": skipped_tickers,
        "業種別集計": sector_summaries,
        "業種・点数帯別集計": sector_score_summaries,
        "業種・検証済み条件別集計": verified_condition_summaries,
        "業種別時系列分割集計": time_split_summaries,
    }


def print_summary(summary: dict) -> None:
    """ターミナルに業種別の要点を表示する。"""
    print(f"業種別リスク検証レポートを保存しました: {REPORT_PATH}")
    print(f"全検証件数: {summary['全検証件数']}")
    for stop_label, rows in summary["業種別集計"].items():
        print(f"\n【利確+2% / 損失ライン{stop_label}】【：業種別】")
        for row in rows:
            print(
                "{sector}: 件数 {count}, 保守的成功率 {rate}%, 損失先行率 {loss_rate}%".format(
                    sector=row["業種"],
                    count=row["検証件数"],
                    rate=row["保守的成功率(%)"],
                    loss_rate=row["損失先行率(%)"],
                )
            )


def main() -> None:
    """価格取得から業種別レポート保存までを実行する。"""
    arguments = parse_arguments()
    if arguments.lookahead_days <= 0:
        raise ValueError("--lookahead-days は1以上を指定してください。")
    if (
        arguments.minimum_samples <= 0
        or arguments.condition_minimum_samples <= 0
        or arguments.time_split_minimum_samples <= 0
    ):
        raise ValueError("最小検証件数は1以上を指定してください。")

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
        raise RuntimeError("業種別検証用のデータを作成できませんでした。")

    summary = create_summary(
        records,
        skipped_tickers,
        arguments.period,
        arguments.lookahead_days,
        arguments.minimum_samples,
        arguments.condition_minimum_samples,
        arguments.time_split_minimum_samples,
    )
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with REPORT_PATH.open("w", encoding="utf-8") as file:
        json.dump(summary, file, ensure_ascii=False, indent=2)
        file.write("\n")

    print_summary(summary)


if __name__ == "__main__":
    main()
