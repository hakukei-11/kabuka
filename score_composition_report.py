# score_composition_report.py

"""スコアを構成する条件ごとの利確・損失ライン到達順を検証する。"""

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
REPORT_PATH = PROJECT_ROOT / "reports" / "score_composition_summary.json"
DEFAULT_PERIOD = "5y"
LOOKAHEAD_DAYS = 20
TARGET_RETURN_PCT = 2.0
STOP_LOSS_PCTS = (3.0, 5.0)
FOCUS_SCORES = (50, 60, 65, 70)
MINIMUM_SAMPLE_SIZE = 30


def parse_arguments() -> argparse.Namespace:
    """コマンドライン引数を取得する。"""
    parser = argparse.ArgumentParser(
        description="スコア構成別の利確・損失ライン到達順を検証します。"
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
        default=MINIMUM_SAMPLE_SIZE,
        help="画面・JSONへ表示する最小検証件数（初期値: 30）",
    )
    return parser.parse_args()


def calculate_component_points(
    row: pd.Series,
    close_today: float,
    close_yesterday: float,
) -> dict[str, int | str]:
    """scoring.pyと同一の配点を、条件ごとの内訳として返す。"""
    is_25ma_touch = bool(row["25MAタッチ"])
    is_low20_touch = bool(row["20日安値タッチ"])
    rsi = float(row["RSI"])
    macd = float(row["MACD"])
    signal = float(row["Signal"])

    if is_25ma_touch and close_today > close_yesterday:
        ma_points, ma_condition = 40, "25MAタッチ・終値上昇"
    elif is_25ma_touch and close_today < close_yesterday:
        ma_points, ma_condition = 20, "25MAタッチ・終値下落"
    elif is_25ma_touch:
        ma_points, ma_condition = 30, "25MAタッチ・終値横ばい"
    else:
        ma_points, ma_condition = 0, "25MA非タッチ"

    if is_low20_touch and close_today > close_yesterday:
        low20_points, low20_condition = 40, "20日安値タッチ・終値上昇"
    elif is_low20_touch:
        low20_points, low20_condition = 20, "20日安値タッチ・終値下落等"
    else:
        low20_points, low20_condition = 0, "20日安値非タッチ"

    if rsi <= 25:
        rsi_points, rsi_condition = 25, "RSI25以下"
    elif rsi <= 30:
        rsi_points, rsi_condition = 20, "RSI26-30"
    elif rsi <= 40:
        rsi_points, rsi_condition = 10, "RSI31-40"
    else:
        rsi_points, rsi_condition = 0, "RSI41超"

    macd_difference = abs(macd - signal)
    if macd > signal and macd_difference < 0.1:
        macd_points, macd_condition = 30, "MACDがSignal超・差0.1未満"
    elif macd > signal:
        macd_points, macd_condition = 20, "MACDがSignal超"
    elif macd_difference < 0.1:
        macd_points, macd_condition = 5, "MACDがSignal以下・差0.1未満"
    else:
        macd_points, macd_condition = 0, "MACDがSignal以下"

    adjustment_points = 0
    adjustment_reason = "補正なし"
    if (
        is_low20_touch
        and close_today <= close_yesterday
        and rsi <= 25
        and macd <= signal
        and macd_difference >= 0.1
    ):
        adjustment_points = 5
        adjustment_reason = "低RSI・20日安値の検証済み補正"
    elif (
        is_25ma_touch
        and 30 < rsi <= 40
        and macd > signal
        and macd_difference >= 0.1
    ):
        adjustment_points = -10
        adjustment_reason = "25MA・RSI31-40の注意補正"

    return {
        "25MA条件": ma_condition,
        "25MA寄与点": ma_points,
        "20日安値条件": low20_condition,
        "20日安値寄与点": low20_points,
        "RSI条件": rsi_condition,
        "RSI寄与点": rsi_points,
        "MACD条件": macd_condition,
        "MACD寄与点": macd_points,
        "検証補正": adjustment_points,
        "補正理由": adjustment_reason,
    }


def create_records(
    prices: pd.DataFrame,
    lookahead_days: int,
) -> tuple[pd.DataFrame, list[str]]:
    """各取引日のスコア構成と利確・損失ライン到達順を記録する。"""
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
            components = calculate_component_points(
                row,
                close_today,
                close_yesterday,
            )
            score = calc_rebound_score(
                is_25ma_touch=bool(row["25MAタッチ"]),
                is_box_bottom_touch=bool(row["20日安値タッチ"]),
                rsi=float(row["RSI"]),
                macd=float(row["MACD"]),
                signal=float(row["Signal"]),
                close_today=close_today,
                close_yesterday=close_yesterday,
            )
            composition = " / ".join(
                [
                    f"25MA:{components['25MA寄与点']}",
                    f"20日安値:{components['20日安値寄与点']}",
                    f"RSI:{components['RSI寄与点']}",
                    f"MACD:{components['MACD寄与点']}",
                    f"補正:{components['検証補正']}",
                ]
            )
            future = data.iloc[index + 1:index + 1 + lookahead_days]
            record = {
                "銘柄コード": ticker,
                "銘柄名": name,
                "取引日": pd.Timestamp(data.index[index]).strftime("%Y-%m-%d"),
                "反発確度スコア": score,
                "スコア構成": composition,
                **components,
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
    label: str,
    stop_loss_pct: float,
) -> dict:
    """指定グループの利確・損失ライン到達順を集計する。"""
    event_column = f"+2%対-{int(stop_loss_pct)}%"
    total = len(group)
    target_first = int((group[event_column] == "利確先行").sum())
    stop_first = int((group[event_column] == "損失先行").sum())
    same_day = int((group[event_column] == "同日両方").sum())
    no_event = int((group[event_column] == "未到達").sum())

    return {
        "条件": label,
        "検証件数": total,
        "利確先行件数": target_first,
        "損失先行件数": stop_first,
        "同日両方件数": same_day,
        "未到達件数": no_event,
        "保守的成功率(%)": round(target_first / total * 100, 2),
        "楽観的成功率(%)": round((target_first + same_day) / total * 100, 2),
        "損失先行率(%)": round(stop_first / total * 100, 2),
    }


def summarize_compositions(
    records: pd.DataFrame,
    score: int,
    stop_loss_pct: float,
    minimum_samples: int,
) -> list[dict]:
    """特定点数を、配点の組み合わせごとに集計する。"""
    score_records = records[records["反発確度スコア"] == score]
    rows = []
    for composition, group in score_records.groupby("スコア構成", sort=True):
        if len(group) < minimum_samples:
            continue
        row = summarize_group(group, str(composition), stop_loss_pct)
        row["反発確度スコア"] = score
        rows.append(row)
    return sorted(
        rows,
        key=lambda item: (-item["保守的成功率(%)"], -item["検証件数"]),
    )


def summarize_individual_conditions(
    records: pd.DataFrame,
    score: int,
    stop_loss_pct: float,
    minimum_samples: int,
) -> list[dict]:
    """特定点数内で、各テクニカル条件の有効性を個別に集計する。"""
    score_records = records[records["反発確度スコア"] == score]
    rows = []
    for column in ["25MA条件", "20日安値条件", "RSI条件", "MACD条件"]:
        for value, group in score_records.groupby(column, sort=True):
            if len(group) < minimum_samples:
                continue
            row = summarize_group(group, f"{column}: {value}", stop_loss_pct)
            row["反発確度スコア"] = score
            rows.append(row)
    return sorted(
        rows,
        key=lambda item: (-item["保守的成功率(%)"], -item["検証件数"]),
    )


def summarize_time_split(
    records: pd.DataFrame,
    score: int,
    stop_loss_pct: float,
    minimum_samples: int,
) -> dict:
    """スコア構成の結果が前半70%・後半30%でも再現するか確認する。"""
    score_records = records[records["反発確度スコア"] == score]
    trade_dates = sorted(score_records["取引日"].unique().tolist())
    split_index = max(0, int(len(trade_dates) * 0.7) - 1)
    split_date = trade_dates[split_index]
    rows = []

    for period_name, period_records in [
        ("前半70%", score_records[score_records["取引日"] <= split_date]),
        ("後半30%", score_records[score_records["取引日"] > split_date]),
    ]:
        for composition, group in period_records.groupby("スコア構成", sort=True):
            if len(group) < minimum_samples:
                continue
            row = summarize_group(group, str(composition), stop_loss_pct)
            row["検証期間"] = period_name
            row["反発確度スコア"] = score
            rows.append(row)

    rows.sort(
        key=lambda item: (item["条件"], item["検証期間"]),
    )
    return {"分割日": split_date, "集計": rows}


def create_summary(
    records: pd.DataFrame,
    skipped_tickers: list[str],
    period: str,
    lookahead_days: int,
    minimum_samples: int,
) -> dict:
    """画面表示・保存用のJSONを作成する。"""
    composition_summaries = {}
    condition_summaries = {}
    time_split_summaries = {}

    for stop_loss_pct in STOP_LOSS_PCTS:
        stop_label = f"-{int(stop_loss_pct)}%"
        composition_summaries[stop_label] = {
            str(score): summarize_compositions(
                records,
                score,
                stop_loss_pct,
                minimum_samples,
            )
            for score in FOCUS_SCORES
        }
        condition_summaries[stop_label] = {
            str(score): summarize_individual_conditions(
                records,
                score,
                stop_loss_pct,
                minimum_samples,
            )
            for score in FOCUS_SCORES
        }
        time_split_summaries[stop_label] = {
            str(score): summarize_time_split(
                records,
                score,
                stop_loss_pct,
                minimum_samples,
            )
            for score in FOCUS_SCORES
        }

    return {
        "作成日時UTC": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "検証条件": {
            "取得期間": period,
            "確認期間(営業日)": lookahead_days,
            "利確目標(%)": TARGET_RETURN_PCT,
            "損失ライン(%)": list(STOP_LOSS_PCTS),
            "対象点数": list(FOCUS_SCORES),
            "最小検証件数": minimum_samples,
            "注意事項": (
                "同日に利確価格と損失価格の両方へ到達した順序は日足だけでは判定できません。"
                "保守的成功率では失敗、楽観的成功率では成功として扱います。"
            ),
        },
        "全検証件数": int(len(records)),
        "除外銘柄": skipped_tickers,
        "スコア構成別集計": composition_summaries,
        "条件別集計": condition_summaries,
        "時系列分割集計": time_split_summaries,
    }


def print_summary(summary: dict) -> None:
    """ターミナルで確認しやすい形に要点を表示する。"""
    print(f"スコア構成別レポートを保存しました: {REPORT_PATH}")
    print(f"全検証件数: {summary['全検証件数']}")

    for stop_label, scores in summary["スコア構成別集計"].items():
        print(f"\n【利確+2% / 損失ライン{stop_label}】")
        for score, rows in scores.items():
            print(f"スコア {score}点")
            for row in rows:
                print(
                    "  {condition}: 件数 {count}, 保守的成功率 {rate}%".format(
                        condition=row["条件"],
                        count=row["検証件数"],
                        rate=row["保守的成功率(%)"],
                    )
                )


def main() -> None:
    """価格取得からスコア構成別レポート保存までを実行する。"""
    arguments = parse_arguments()
    if arguments.lookahead_days <= 0:
        raise ValueError("--lookahead-days は1以上を指定してください。")
    if arguments.minimum_samples <= 0:
        raise ValueError("--minimum-samples は1以上を指定してください。")

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
        raise RuntimeError("スコア構成別検証用のデータを作成できませんでした。")

    summary = create_summary(
        records,
        skipped_tickers,
        arguments.period,
        arguments.lookahead_days,
        arguments.minimum_samples,
    )
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with REPORT_PATH.open("w", encoding="utf-8") as file:
        json.dump(summary, file, ensure_ascii=False, indent=2)
        file.write("\n")

    print_summary(summary)


if __name__ == "__main__":
    main()
