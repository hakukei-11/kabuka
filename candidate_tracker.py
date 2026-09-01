# candidate_tracker.py

"""日次CSVの候補を保存し、以後20営業日の終値で追跡する。"""

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from sectors import get_sector

DATA_DIRECTORY = Path("data")
REPORT_DIRECTORY = Path("reports")
REPORT_PATH = REPORT_DIRECTORY / "candidate_tracking.json"
SCORE_VERSION = "2026-09-01"
SCORE_THRESHOLD = 50
LOOKAHEAD_DAYS = 20
TARGET_RETURN_PCT = 2.0
STOP_LINES = (-3.0, -5.0)


def to_native(value):
    """JSONへ保存できるPythonの基本型へ変換する。"""
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def read_csv(path: Path) -> pd.DataFrame:
    """UTF-8 BOM付きの日次CSVを読み込む。"""
    return pd.read_csv(path, encoding="utf-8-sig")


def get_daily_csv_paths() -> list[Path]:
    """日次CSVをファイル名順で返す。"""
    return sorted(DATA_DIRECTORY.glob("*/*/data_*.csv"))


def load_latest_daily_csv() -> tuple[pd.DataFrame, Path]:
    """最新の日次CSVを読み込む。"""
    paths = get_daily_csv_paths()
    if not paths:
        raise FileNotFoundError("data配下に日次CSVがありません。")
    latest_path = paths[-1]
    return read_csv(latest_path), latest_path


def is_true(value) -> bool:
    """CSVの真偽値を安全に判定する。"""
    return str(value).strip().lower() in {"true", "1", "yes"}


def classify_candidate(row: pd.Series) -> str:
    """検証済み候補の条件に応じて分類名を返す。"""
    low20_touch = is_true(row.get("20日安値タッチ"))
    ma25_touch = is_true(row.get("25MAタッチ"))
    previous_change = float(row.get("前日比", 0))
    rsi = float(row.get("RSI", 999))
    macd = float(row.get("MACD", 0))
    signal = float(row.get("Signal", 0))
    macd_difference = abs(macd - signal)

    if low20_touch and previous_change > 0 and rsi <= 25 and macd <= signal:
        return "優先候補: 20日安値・終値上昇・RSI25以下"
    if (
        low20_touch
        and previous_change <= 0
        and rsi <= 25
        and macd <= signal
        and macd_difference >= 0.1
    ):
        return "逆張り優先候補: 20日安値・終値下落等・RSI25以下"
    if (
        ma25_touch
        and not low20_touch
        and previous_change > 0
        and 30 < rsi <= 40
        and macd > signal
        and macd_difference >= 0.1
    ):
        return "注意候補: 25MA・RSI31-40・MACD上向き"
    return "スコア50点以上"


def make_candidate_records(frame: pd.DataFrame, source_path: Path) -> list[dict]:
    """最新CSVからスコア50点以上の候補レコードを作る。"""
    required_columns = {"取引日", "銘柄コード", "銘柄名", "終値", "反発確度スコア"}
    missing_columns = required_columns - set(frame.columns)
    if missing_columns:
        raise ValueError(f"最新CSVに必要な列がありません: {sorted(missing_columns)}")

    candidates = frame[pd.to_numeric(frame["反発確度スコア"], errors="coerce") >= SCORE_THRESHOLD]
    records = []
    for _, row in candidates.iterrows():
        ticker = str(row["銘柄コード"])
        record = {
            "スコア仕様バージョン": SCORE_VERSION,
            "取引日": str(row["取引日"]),
            "銘柄コード": ticker,
            "銘柄名": str(row["銘柄名"]),
            "業種": get_sector(ticker),
            "候補分類": classify_candidate(row),
            "終値": float(row["終値"]),
            "反発確度スコア": int(row["反発確度スコア"]),
            "RSI": to_native(row.get("RSI")),
            "MACD": to_native(row.get("MACD")),
            "Signal": to_native(row.get("Signal")),
            "25MAタッチ": is_true(row.get("25MAタッチ")),
            "20日安値タッチ": is_true(row.get("20日安値タッチ")),
            "判定": str(row.get("判定", "")),
            "元CSV": str(source_path).replace("\\", "/"),
        }
        records.append(record)
    return records


def load_close_history() -> dict[str, list[tuple[pd.Timestamp, float]]]:
    """日次CSV群から銘柄ごとの終値時系列を組み立てる。"""
    rows: list[pd.DataFrame] = []
    for path in get_daily_csv_paths():
        try:
            frame = read_csv(path)
        except (OSError, UnicodeDecodeError, pd.errors.ParserError):
            continue
        required_columns = {"取引日", "銘柄コード", "終値"}
        if required_columns.issubset(frame.columns):
            rows.append(frame[["取引日", "銘柄コード", "終値"]])

    if not rows:
        return {}

    history = pd.concat(rows, ignore_index=True)
    history["取引日"] = pd.to_datetime(history["取引日"], errors="coerce")
    history["終値"] = pd.to_numeric(history["終値"], errors="coerce")
    history = history.dropna(subset=["取引日", "銘柄コード", "終値"])
    history = history.drop_duplicates(subset=["取引日", "銘柄コード"], keep="last")
    history = history.sort_values(["銘柄コード", "取引日"])

    result: dict[str, list[tuple[pd.Timestamp, float]]] = {}
    for ticker, ticker_frame in history.groupby("銘柄コード"):
        result[str(ticker)] = list(
            zip(ticker_frame["取引日"], ticker_frame["終値"], strict=True)
        )
    return result


def evaluate_stop_line(
    future_prices: list[tuple[pd.Timestamp, float]],
    entry_close: float,
    stop_line: float,
) -> dict:
    """終値ベースで利確と損失ラインの先後を判定する。"""
    target_price = entry_close * (1 + TARGET_RETURN_PCT / 100)
    stop_price = entry_close * (1 + stop_line / 100)
    for trade_date, close in future_prices:
        if close >= target_price:
            return {"結果": "利確先行", "結果取引日": trade_date.strftime("%Y-%m-%d")}
        if close <= stop_price:
            return {"結果": "損失先行", "結果取引日": trade_date.strftime("%Y-%m-%d")}
    return {"結果": "未到達", "結果取引日": None}


def evaluate_record(record: dict, close_history: dict[str, list[tuple[pd.Timestamp, float]]]) -> dict:
    """候補レコードへ将来終値に基づく追跡結果を付加する。"""
    entry_date = pd.Timestamp(record["取引日"])
    ticker_history = close_history.get(record["銘柄コード"], [])
    future_prices = [(date, close) for date, close in ticker_history if date > entry_date][:LOOKAHEAD_DAYS]
    entry_close = float(record["終値"])
    result = dict(record)
    result["追跡済み営業日"] = len(future_prices)
    result["追跡状況"] = "検証完了" if len(future_prices) >= LOOKAHEAD_DAYS else "追跡中"

    if future_prices:
        closes = [close for _, close in future_prices]
        result["最大終値リターン(%)"] = round((max(closes) / entry_close - 1) * 100, 2)
        result["最新終値リターン(%)"] = round((closes[-1] / entry_close - 1) * 100, 2)
    else:
        result["最大終値リターン(%)"] = None
        result["最新終値リターン(%)"] = None

    for stop_line in STOP_LINES:
        prefix = f"+2%対{int(stop_line)}%"
        event = evaluate_stop_line(future_prices, entry_close, stop_line)
        result[f"{prefix}結果"] = event["結果"] if result["追跡状況"] == "検証完了" else "追跡中"
        result[f"{prefix}結果取引日"] = event["結果取引日"]
    return result


def summarize(records: list[dict]) -> dict:
    """画面表示用の全体・分類別集計を作る。"""
    completed = [record for record in records if record["追跡状況"] == "検証完了"]
    overview = {
        "候補件数": len(records),
        "追跡中件数": len(records) - len(completed),
        "検証完了件数": len(completed),
    }
    summaries = []
    for stop_line in STOP_LINES:
        prefix = f"+2%対{int(stop_line)}%"
        target_first = sum(record.get(f"{prefix}結果") == "利確先行" for record in completed)
        stop_first = sum(record.get(f"{prefix}結果") == "損失先行" for record in completed)
        unresolved = sum(record.get(f"{prefix}結果") == "未到達" for record in completed)
        summaries.append(
            {
                "条件": f"利確+2% / 損失ライン{int(stop_line)}%",
                "検証完了件数": len(completed),
                "利確先行件数": target_first,
                "損失先行件数": stop_first,
                "未到達件数": unresolved,
                "利確先行率(%)": round(target_first / len(completed) * 100, 2) if completed else None,
            }
        )

    by_category = []
    category_groups = pd.DataFrame(records).groupby("候補分類") if records else []
    for category, category_records in category_groups:
        category_completed = category_records[category_records["追跡状況"] == "検証完了"]
        by_category.append(
            {
                "候補分類": category,
                "候補件数": len(category_records),
                "検証完了件数": len(category_completed),
                "+2%対-3%利確先行率(%)": (
                    round((category_completed["+2%対-3%結果"] == "利確先行").mean() * 100, 2)
                    if not category_completed.empty
                    else None
                ),
                "+2%対-5%利確先行率(%)": (
                    round((category_completed["+2%対-5%結果"] == "利確先行").mean() * 100, 2)
                    if not category_completed.empty
                    else None
                ),
            }
        )
    return {"全体": overview, "利確・損失ライン集計": summaries, "候補分類別集計": by_category}


def load_existing_records() -> list[dict]:
    """前回までの候補記録を読み込む。"""
    try:
        with REPORT_PATH.open("r", encoding="utf-8") as file:
            return json.load(file).get("候補一覧", [])
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def main() -> None:
    """候補の追加保存と、既存候補の追跡更新を実行する。"""
    latest_frame, latest_path = load_latest_daily_csv()
    latest_records = make_candidate_records(latest_frame, latest_path)
    existing_records = load_existing_records()
    record_map = {
        (record["スコア仕様バージョン"], record["取引日"], record["銘柄コード"]): record
        for record in existing_records
    }
    for record in latest_records:
        record_map[(record["スコア仕様バージョン"], record["取引日"], record["銘柄コード"])] = record

    close_history = load_close_history()
    tracked_records = [
        evaluate_record(record, close_history)
        for record in sorted(record_map.values(), key=lambda item: (item["取引日"], item["銘柄コード"]))
    ]
    REPORT_DIRECTORY.mkdir(exist_ok=True)
    report = {
        "作成日時UTC": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "検証条件": {
            "候補スコア下限": SCORE_THRESHOLD,
            "スコア仕様バージョン": SCORE_VERSION,
            "利確目標(%)": TARGET_RETURN_PCT,
            "損失ライン(%)": list(STOP_LINES),
            "確認期間(営業日)": LOOKAHEAD_DAYS,
            "価格基準": "日次CSVの終値",
            "注意事項": "終値だけで判定する実運用追跡です。同日中の利確・損失ライン到達順は判定しません。売買推奨や将来の利益を保証するものではありません。",
        },
        "最新候補CSV": str(latest_path).replace("\\", "/"),
        **summarize(tracked_records),
        "候補一覧": tracked_records,
    }
    with REPORT_PATH.open("w", encoding="utf-8") as file:
        json.dump(report, file, ensure_ascii=False, indent=2)

    print(f"実運用追跡レポートを保存しました: {REPORT_PATH}")
    print(f"本日追加候補: {len(latest_records)}件")
    print(f"追跡中: {report['全体']['追跡中件数']}件 / 検証完了: {report['全体']['検証完了件数']}件")


if __name__ == "__main__":
    main()
