# risk_backtest.py

"""過去日足から、2%目標到達と下落リスクを集計する。"""

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

from tickers import TICKERS


PROJECT_ROOT = Path(__file__).resolve().parent
REPORT_PATH = PROJECT_ROOT / "reports" / "risk_backtest_summary.json"
LOOKAHEAD_DAYS = 20
TARGET_RETURN_PCT = 2.0
STOP_LOSS_PCTS = (3.0, 5.0)


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
        if len(data) <= LOOKAHEAD_DAYS:
            continue
        for index in range(len(data) - LOOKAHEAD_DAYS):
            entry = float(data["Close"].iloc[index])
            future = data.iloc[index + 1:index + 1 + LOOKAHEAD_DAYS]
            max_drawdown = ((float(future["Low"].min()) - entry) / entry) * 100
            record = {
                "銘柄コード": ticker,
                "銘柄名": name,
                "+2%到達": bool((future["High"] >= entry * 1.02).any()),
                "最大含み損(%)": max_drawdown,
                "20日後リターン(%)": ((float(future["Close"].iloc[-1]) - entry) / entry) * 100,
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
        "銘柄別集計": summarize_records(frame, "銘柄コード"),
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with REPORT_PATH.open("w", encoding="utf-8") as file:
        json.dump(summary, file, ensure_ascii=False, indent=2)
        file.write("\n")
    print(f"リスクバックテスト結果を保存しました: {REPORT_PATH}")


if __name__ == "__main__":
    main()
