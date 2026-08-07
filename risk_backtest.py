# risk_backtest.py

"""過去日足から、2%目標到達と下落リスクを集計する。"""

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

from analysis_engine import prepare_dataframe
from tickers import TICKERS


PROJECT_ROOT = Path(__file__).resolve().parent
REPORT_PATH = PROJECT_ROOT / "reports" / "risk_backtest_summary.json"
LOOKAHEAD_DAYS = 20
TARGET_RETURN_PCT = 2.0
STOP_LOSS_PCTS = (3.0, 5.0)
ROUND_TRIP_COST_PCTS = (0.0, 0.1, 0.2, 0.3)
REFERENCE_STOP_LOSS_PCT = 5.0
REFERENCE_ROUND_TRIP_COST_PCT = 0.1


def summarize_records(records: pd.DataFrame, group_column: str) -> list[dict]:
    """全体または銘柄別のリスク結果を集計する。"""
    result = []
    for value, group in records.groupby(group_column, sort=True):
        result.append({
            group_column: str(value),
            "検証件数": len(group),
            "+2%到達件数": int((group["+2%到達"] == True).sum()),
            "-3%到達件数": int((group["-3%到達"] == True).sum()),
            "-5%到達件数": int((group["-5%到達"] == True).sum()),
            "平均最大含み損(%)": round(group["最大含み損(%)"].mean(), 2),
            "平均20日後リターン(%)": round(group["20日後リターン(%)"].mean(), 2),
        })
    return result


def get_first_event(future: pd.DataFrame, target_price: float, stop_price: float) -> str:
    """日足順に利確・損失ラインの先後を判定する。"""
    for _, row in future.iterrows():
        target_hit = float(row["High"]) >= target_price
        stop_hit = float(row["Low"]) <= stop_price
        if target_hit and stop_hit:
            return "同日両方"
        if target_hit:
            return "利確先行"
        if stop_hit:
            return "損失先行"
    return "未到達"


def summarize_event_order(records: pd.DataFrame, stop_loss_pct: float) -> list[dict]:
    """全銘柄での利確・損失ラインの先後を集計する。"""
    column = f"+2%対-{int(stop_loss_pct)}%先後"
    counts = records[column].value_counts()
    total = len(records)
    target_first = int(counts.get("利確先行", 0))
    stop_first = int(counts.get("損失先行", 0))
    ambiguous = int(counts.get("同日両方", 0))
    no_event = int(counts.get("未到達", 0))
    return [{
        "損失ライン": f"-{int(stop_loss_pct)}%",
        "検証件数": total,
        "利確先行": target_first,
        "損失先行": stop_first,
        "同日両方（順序不明）": ambiguous,
        "未到達": no_event,
        "保守成功率(%)": round(target_first / total * 100, 2),
        "楽観成功率(%)": round((target_first + ambiguous) / total * 100, 2),
    }]


def summarize_expected_return(records: pd.DataFrame, stop_loss_pct: float) -> list[dict]:
    """利確・損失・未到達時の決済結果から期待リターンを集計する。"""
    stop_label = f"-{int(stop_loss_pct)}%"
    conservative_column = f"{stop_label}保守リターン(%)"
    optimistic_column = f"{stop_label}楽観リターン(%)"
    event_column = f"+2%対-{int(stop_loss_pct)}%先後"
    no_event = records[records[event_column] == "未到達"]
    conservative = records[conservative_column]
    optimistic = records[optimistic_column]

    return [{
        "損失ライン": stop_label,
        "保守平均リターン(%)": round(conservative.mean(), 3),
        "楽観平均リターン(%)": round(optimistic.mean(), 3),
        "保守勝率(%)": round((conservative > 0).mean() * 100, 2),
        "楽観勝率(%)": round((optimistic > 0).mean() * 100, 2),
        "未到達件数": int(len(no_event)),
        "未到達時平均リターン(%)": round(
            no_event["20日後リターン(%)"].mean(),
            3,
        ) if not no_event.empty else None,
    }]


def summarize_time_split_returns(records: pd.DataFrame) -> dict:
    """前半70%と後半30%で期待リターンの再現性を比較する。"""
    trade_dates = sorted(records["取引日"].unique().tolist())
    split_index = max(0, int(len(trade_dates) * 0.7) - 1)
    split_date = trade_dates[split_index]
    summaries = []

    for stop_loss_pct in STOP_LOSS_PCTS:
        stop_label = f"-{int(stop_loss_pct)}%"
        for period_name, period_records in [
            ("前半70%", records[records["取引日"] <= split_date]),
            ("後半30%", records[records["取引日"] > split_date]),
        ]:
            for scenario_name, column in [
                ("保守", f"{stop_label}保守リターン(%)"),
                ("楽観", f"{stop_label}楽観リターン(%)"),
            ]:
                summaries.append({
                    "損失ライン": stop_label,
                    "検証期間": period_name,
                    "判定": scenario_name,
                    "検証件数": int(len(period_records)),
                    "平均リターン(%)": round(period_records[column].mean(), 3),
                    "勝率(%)": round((period_records[column] > 0).mean() * 100, 2),
                })

    return {"分割日": split_date, "集計": summaries}


def summarize_cost_sensitivity(records: pd.DataFrame) -> dict:
    """往復コストを差し引いた保守ケースのリターンを比較する。"""
    trade_dates = sorted(records["取引日"].unique().tolist())
    split_index = max(0, int(len(trade_dates) * 0.7) - 1)
    split_date = trade_dates[split_index]
    periods = [
        ("全期間", records),
        ("後半30%", records[records["取引日"] > split_date]),
    ]
    summaries = []

    for stop_loss_pct in STOP_LOSS_PCTS:
        column = f"-{int(stop_loss_pct)}%保守リターン(%)"
        for period_name, period_records in periods:
            for cost_pct in ROUND_TRIP_COST_PCTS:
                net_return = period_records[column] - cost_pct
                summaries.append({
                    "損失ライン": f"-{int(stop_loss_pct)}%",
                    "検証期間": period_name,
                    "往復コスト(%)": cost_pct,
                    "コスト後平均リターン(%)": round(net_return.mean(), 3),
                    "コスト後勝率(%)": round((net_return > 0).mean() * 100, 2),
                })

    return {"分割日": split_date, "集計": summaries}


def summarize_ticker_cost_adjusted_returns(records: pd.DataFrame) -> dict:
    """後半30%の銘柄別コスト後リターンを比較する。"""
    trade_dates = sorted(records["取引日"].unique().tolist())
    split_index = max(0, int(len(trade_dates) * 0.7) - 1)
    split_date = trade_dates[split_index]
    latter_records = records[records["取引日"] > split_date]
    return_column = f"-{int(REFERENCE_STOP_LOSS_PCT)}%保守リターン(%)"
    summaries = []

    for ticker, group in latter_records.groupby("銘柄コード", sort=True):
        net_return = group[return_column] - REFERENCE_ROUND_TRIP_COST_PCT
        summaries.append({
            "銘柄コード": str(ticker),
            "銘柄名": str(group["銘柄名"].iloc[0]),
            "検証件数": int(len(group)),
            "損失ライン": f"-{int(REFERENCE_STOP_LOSS_PCT)}%",
            "往復コスト(%)": REFERENCE_ROUND_TRIP_COST_PCT,
            "コスト後平均リターン(%)": round(net_return.mean(), 3),
            "コスト後勝率(%)": round((net_return > 0).mean() * 100, 2),
            "判定": "プラス" if net_return.mean() > 0 else "マイナス",
        })

    summaries.sort(key=lambda item: item["コスト後平均リターン(%)"], reverse=True)
    return {"分割日": split_date, "集計": summaries}


def summarize_ticker_cost_reproducibility(records: pd.DataFrame) -> dict:
    """前半で選んだ銘柄の後半コスト後リターンを検証する。"""
    trade_dates = sorted(records["取引日"].unique().tolist())
    split_index = max(0, int(len(trade_dates) * 0.7) - 1)
    split_date = trade_dates[split_index]
    first_records = records[records["取引日"] <= split_date]
    latter_records = records[records["取引日"] > split_date]
    return_column = f"-{int(REFERENCE_STOP_LOSS_PCT)}%保守リターン(%)"
    summaries = []

    for ticker, first_group in first_records.groupby("銘柄コード", sort=True):
        latter_group = latter_records[latter_records["銘柄コード"] == ticker]
        if latter_group.empty:
            continue
        first_net_return = first_group[return_column] - REFERENCE_ROUND_TRIP_COST_PCT
        latter_net_return = latter_group[return_column] - REFERENCE_ROUND_TRIP_COST_PCT
        selected_in_first = first_net_return.mean() > 0
        latter_positive = latter_net_return.mean() > 0
        summaries.append({
            "銘柄コード": str(ticker),
            "銘柄名": str(first_group["銘柄名"].iloc[0]),
            "前半検証件数": int(len(first_group)),
            "前半コスト後平均リターン(%)": round(first_net_return.mean(), 3),
            "前半選定": "採用候補" if selected_in_first else "対象外",
            "後半検証件数": int(len(latter_group)),
            "後半コスト後平均リターン(%)": round(latter_net_return.mean(), 3),
            "後半検証": "プラス" if latter_positive else "マイナス",
            "再現性判定": "維持" if selected_in_first and latter_positive else "未確認",
        })

    summaries.sort(
        key=lambda item: item["後半コスト後平均リターン(%)"],
        reverse=True,
    )
    selected = [item for item in summaries if item["前半選定"] == "採用候補"]
    reproduced = [item for item in selected if item["再現性判定"] == "維持"]
    return {
        "分割日": split_date,
        "基準": {
            "損失ライン": f"-{int(REFERENCE_STOP_LOSS_PCT)}%",
            "往復コスト(%)": REFERENCE_ROUND_TRIP_COST_PCT,
        },
        "前半採用候補数": len(selected),
        "後半でプラス維持した銘柄数": len(reproduced),
        "集計": summaries,
    }


def summarize_condition_cost_reproducibility(records: pd.DataFrame) -> dict:
    """事前定義した技術条件を前半・後半のコスト後成績で比較する。"""
    trade_dates = sorted(records["取引日"].unique().tolist())
    split_index = max(0, int(len(trade_dates) * 0.7) - 1)
    split_date = trade_dates[split_index]
    first_records = records[records["取引日"] <= split_date]
    latter_records = records[records["取引日"] > split_date]
    return_column = f"-{int(REFERENCE_STOP_LOSS_PCT)}%保守リターン(%)"
    conditions = [
        ("全銘柄（基準）", lambda frame: frame),
        ("RSI 40以下", lambda frame: frame[frame["RSI40以下"]]),
        ("MACDがSignal以下", lambda frame: frame[frame["MACDシグナル以下"]]),
        ("25MAタッチ", lambda frame: frame[frame["25MAタッチ"]]),
        (
            "RSI 40以下 かつ MACDがSignal以下",
            lambda frame: frame[frame["RSI40以下"] & frame["MACDシグナル以下"]],
        ),
        ("20日安値タッチ", lambda frame: frame[frame["20日安値タッチ"]]),
    ]
    summaries = []

    for condition_name, filter_records in conditions:
        first_group = filter_records(first_records)
        latter_group = filter_records(latter_records)
        first_net_return = first_group[return_column] - REFERENCE_ROUND_TRIP_COST_PCT
        latter_net_return = latter_group[return_column] - REFERENCE_ROUND_TRIP_COST_PCT
        summaries.append({
            "条件": condition_name,
            "前半検証件数": int(len(first_group)),
            "前半コスト後平均リターン(%)": round(first_net_return.mean(), 3),
            "後半検証件数": int(len(latter_group)),
            "後半コスト後平均リターン(%)": round(latter_net_return.mean(), 3),
            "後半コスト後勝率(%)": round((latter_net_return > 0).mean() * 100, 2),
            "後半判定": "プラス" if latter_net_return.mean() > 0 else "マイナス",
        })

    return {
        "分割日": split_date,
        "基準": {
            "損失ライン": f"-{int(REFERENCE_STOP_LOSS_PCT)}%",
            "往復コスト(%)": REFERENCE_ROUND_TRIP_COST_PCT,
        },
        "集計": summaries,
    }


def main() -> None:
    """2年分の日足を使ってリスク指標を保存する。"""
    prices = yf.download(
        list(TICKERS.keys()), period="2y", group_by="ticker",
        threads=True, auto_adjust=True, progress=False,
    )
    records = []
    for ticker, name in TICKERS.items():
        try:
            data = prices[ticker].dropna(how="all")
        except (KeyError, TypeError):
            continue
        data = prepare_dataframe(data)
        if data is None or len(data) <= LOOKAHEAD_DAYS:
            continue
        for index in range(len(data) - LOOKAHEAD_DAYS):
            if pd.isna(data["RSI"].iloc[index]) or pd.isna(data["25MA"].iloc[index]):
                continue
            entry = float(data["Close"].iloc[index])
            future = data.iloc[index + 1:index + 1 + LOOKAHEAD_DAYS]
            max_drawdown = ((float(future["Low"].min()) - entry) / entry) * 100
            record = {
                "銘柄コード": ticker,
                "銘柄名": name,
                "取引日": pd.Timestamp(data.index[index]).strftime("%Y-%m-%d"),
                "+2%到達": bool((future["High"] >= entry * 1.02).any()),
                "最大含み損(%)": max_drawdown,
                "20日後リターン(%)": ((float(future["Close"].iloc[-1]) - entry) / entry) * 100,
                "25MAタッチ": bool(data["25MAタッチ"].iloc[index]),
                "20日安値タッチ": bool(data["20日安値タッチ"].iloc[index]),
                "RSI40以下": bool(data["RSI40以下"].iloc[index]),
                "MACDシグナル以下": bool(data["MACDシグナル以下"].iloc[index]),
            }
            for stop_loss_pct in STOP_LOSS_PCTS:
                record[f"-{int(stop_loss_pct)}%到達"] = bool(
                    (future["Low"] <= entry * (1 - stop_loss_pct / 100)).any()
                )
                record[f"+2%対-{int(stop_loss_pct)}%先後"] = get_first_event(
                    future=future,
                    target_price=entry * (1 + TARGET_RETURN_PCT / 100),
                    stop_price=entry * (1 - stop_loss_pct / 100),
                )
                event = record[f"+2%対-{int(stop_loss_pct)}%先後"]
                stop_label = f"-{int(stop_loss_pct)}%"
                if event == "利確先行":
                    conservative_return = TARGET_RETURN_PCT
                    optimistic_return = TARGET_RETURN_PCT
                elif event == "損失先行":
                    conservative_return = -stop_loss_pct
                    optimistic_return = -stop_loss_pct
                elif event == "同日両方":
                    conservative_return = -stop_loss_pct
                    optimistic_return = TARGET_RETURN_PCT
                else:
                    conservative_return = record["20日後リターン(%)"]
                    optimistic_return = record["20日後リターン(%)"]
                record[f"{stop_label}保守リターン(%)"] = conservative_return
                record[f"{stop_label}楽観リターン(%)"] = optimistic_return
            records.append(record)
    frame = pd.DataFrame(records)
    summary = {
        "作成日時UTC": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "検証条件": {"確認期間(取引日)": LOOKAHEAD_DAYS, "利確目標(%)": TARGET_RETURN_PCT, "損失閾値(%)": list(STOP_LOSS_PCTS)},
        "全体集計": summarize_records(frame.assign(全体="全銘柄"), "全体"),
        "先後判定集計": [
            *summarize_event_order(frame, 3.0),
            *summarize_event_order(frame, 5.0),
        ],
        "期待リターン集計": [
            *summarize_expected_return(frame, 3.0),
            *summarize_expected_return(frame, 5.0),
        ],
        "時系列分割期待リターン": summarize_time_split_returns(frame),
        "コスト感度分析": summarize_cost_sensitivity(frame),
        "銘柄別コスト後分析": summarize_ticker_cost_adjusted_returns(frame),
        "銘柄別コスト後再現性": summarize_ticker_cost_reproducibility(frame),
        "条件別コスト後再現性": summarize_condition_cost_reproducibility(frame),
        "銘柄別集計": summarize_records(frame, "銘柄コード"),
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with REPORT_PATH.open("w", encoding="utf-8") as file:
        json.dump(summary, file, ensure_ascii=False, indent=2)
        file.write("\n")
    print(f"リスクバックテスト結果を保存しました: {REPORT_PATH}")


if __name__ == "__main__":
    main()
