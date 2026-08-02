# backtest.py

"""日次CSVを使い、終値ベースの2%到達率を検証する。"""

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIRECTORY = PROJECT_ROOT / "data"
REPORT_DIRECTORY = PROJECT_ROOT / "reports"
REPORT_PATH = REPORT_DIRECTORY / "backtest_summary.json"
REQUIRED_COLUMNS = {
    "銘柄コード",
    "銘柄名",
    "終値",
    "判定",
    "反発確度スコア",
}


def parse_arguments() -> argparse.Namespace:
    """コマンドライン引数を取得する。"""
    parser = argparse.ArgumentParser(
        description="日次CSVから終値ベースの2%到達率を検証します。"
    )
    parser.add_argument(
        "--lookahead-days",
        type=int,
        default=20,
        help="2%%到達を確認する将来取引日数（初期値: 20）",
    )
    parser.add_argument(
        "--target-return-pct",
        type=float,
        default=2.0,
        help="目標上昇率（初期値: 2.0%%）",
    )
    return parser.parse_args()


def get_source_date(csv_path: Path) -> pd.Timestamp:
    """CSVファイル名から出力日を取得する。"""
    matched = re.fullmatch(r"data_(\d{8})\.csv", csv_path.name)
    if matched is None:
        return pd.NaT

    return pd.to_datetime(matched.group(1), format="%Y%m%d", errors="coerce")


def load_history(data_directory: Path) -> tuple[pd.DataFrame, int]:
    """data配下の日次CSVを読み込み、銘柄・取引日ごとの最新行に整理する。"""
    csv_paths = sorted(data_directory.rglob("data_*.csv"))
    frames = []

    for csv_path in csv_paths:
        try:
            frame = pd.read_csv(csv_path, encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError, pd.errors.ParserError) as error:
            print(f"CSVを読み込めませんでした: {csv_path} ({error})")
            continue

        missing_columns = REQUIRED_COLUMNS - set(frame.columns)
        if missing_columns:
            print(f"必要な列が不足しているため除外します: {csv_path} ({sorted(missing_columns)})")
            continue

        frame = frame.copy()
        source_date = get_source_date(csv_path)
        frame["CSV出力日"] = source_date

        # 旧CSVには取引日がないため、出力日を暫定的な取引日として使う。
        # 新CSVはCSV内の取引日を優先する。
        if "取引日" not in frame.columns:
            frame["取引日"] = source_date
        frames.append(frame)

    if not frames:
        return pd.DataFrame(), len(csv_paths)

    history = pd.concat(frames, ignore_index=True)
    history["取引日"] = pd.to_datetime(history["取引日"], errors="coerce")
    history["CSV出力日"] = pd.to_datetime(history["CSV出力日"], errors="coerce")
    history["終値"] = pd.to_numeric(history["終値"], errors="coerce")
    history["反発確度スコア"] = pd.to_numeric(
        history["反発確度スコア"],
        errors="coerce",
    )
    history["銘柄コード"] = history["銘柄コード"].astype(str)

    history = history.dropna(
        subset=["取引日", "CSV出力日", "終値", "反発確度スコア"]
    )
    history = history.sort_values(
        ["銘柄コード", "取引日", "CSV出力日"]
    )

    # 休日や再実行で同じ取引日が複数保存された場合は、最新CSVの値を採用する。
    history = history.drop_duplicates(
        subset=["銘柄コード", "取引日"],
        keep="last",
    ).reset_index(drop=True)

    return history, len(csv_paths)


def get_score_band(score: float) -> str:
    """スコアを集計用の帯に変換する。"""
    if score >= 80:
        return "80点以上"
    if score >= 60:
        return "60-79点"
    if score >= 50:
        return "50-59点"
    return "0-49点"


def create_trade_records(
    history: pd.DataFrame,
    lookahead_days: int,
    target_return_pct: float,
) -> pd.DataFrame:
    """各銘柄・各取引日の2%到達状況を作成する。"""
    records = []
    target_multiplier = 1 + target_return_pct / 100

    for ticker, ticker_history in history.groupby("銘柄コード", sort=True):
        ticker_history = ticker_history.sort_values("取引日").reset_index(drop=True)

        for index, row in ticker_history.iterrows():
            entry_close = float(row["終値"])
            target_price = entry_close * target_multiplier
            future_history = ticker_history.iloc[index + 1 : index + 1 + lookahead_days]
            future_days = len(future_history)
            is_complete = future_days >= lookahead_days

            reached_history = future_history[
                future_history["終値"] >= target_price
            ]

            if not is_complete:
                # 20取引日がそろう前の候補は、途中で目標へ到達していても
                # スコア成功率の分母・分子には含めない。
                result_status = "検証中"
                if not reached_history.empty:
                    first_reached = reached_history.iloc[0]
                    reached_trade_date = first_reached["取引日"]
                    days_to_target = int(first_reached.name - index)
                else:
                    reached_trade_date = pd.NaT
                    days_to_target = None
            elif not reached_history.empty:
                first_reached = reached_history.iloc[0]
                result_status = "成功"
                reached_trade_date = first_reached["取引日"]
                days_to_target = int(first_reached.name - index)
            else:
                result_status = "未到達"
                reached_trade_date = pd.NaT
                days_to_target = None

            highest_close = (
                float(future_history["終値"].max())
                if not future_history.empty
                else None
            )
            max_return_pct = (
                ((highest_close - entry_close) / entry_close) * 100
                if highest_close is not None
                else None
            )

            records.append(
                {
                    "銘柄コード": ticker,
                    "銘柄名": row["銘柄名"],
                    "取引日": row["取引日"],
                    "終値": entry_close,
                    "目標売値": target_price,
                    "反発確度スコア": int(row["反発確度スコア"]),
                    "スコア帯": get_score_band(float(row["反発確度スコア"])),
                    "判定": row["判定"],
                    "将来取引日数": future_days,
                    "検証状態": result_status,
                    "2%到達取引日": reached_trade_date,
                    "到達日数": days_to_target,
                    "最高終値": highest_close,
                    "最大上昇率(%)": max_return_pct,
                }
            )

    return pd.DataFrame(records)


def summarize_records(records: pd.DataFrame, group_column: str) -> list[dict]:
    """スコア帯・判定・銘柄ごとの成功率を集計する。"""
    if records.empty:
        return []

    summaries = []
    for group_value, group in records.groupby(group_column, dropna=False, sort=True):
        completed = group[group["検証状態"].isin(["成功", "未到達"])]
        success = completed[completed["検証状態"] == "成功"]
        success_rate = (
            (len(success) / len(completed)) * 100
            if not completed.empty
            else None
        )
        average_days = (
            float(success["到達日数"].mean())
            if not success.empty
            else None
        )

        summaries.append(
            {
                group_column: str(group_value),
                "候補件数": int(len(group)),
                "検証完了件数": int(len(completed)),
                "成功件数": int(len(success)),
                "未到達件数": int(len(completed) - len(success)),
                "検証中件数": int((group["検証状態"] == "検証中").sum()),
                "成功率(%)": round(success_rate, 2)
                if success_rate is not None
                else None,
                "平均到達日数": round(average_days, 2)
                if average_days is not None
                else None,
            }
        )

    return summaries


def convert_records_for_json(records: pd.DataFrame) -> list[dict]:
    """DataFrameをJSONへ安全に書き出せる辞書一覧に変換する。"""
    if records.empty:
        return []

    json_records = records.copy()
    for column in ["取引日", "2%到達取引日"]:
        json_records[column] = json_records[column].apply(
            lambda value: value.strftime("%Y-%m-%d")
            if pd.notna(value)
            else None
        )

    for column in ["終値", "目標売値", "最高終値", "最大上昇率(%)"]:
        json_records[column] = json_records[column].apply(
            lambda value: round(float(value), 3)
            if pd.notna(value)
            else None
        )

    json_records = json_records.where(pd.notna(json_records), None)
    return json_records.to_dict(orient="records")


def create_summary(
    history: pd.DataFrame,
    records: pd.DataFrame,
    csv_file_count: int,
    lookahead_days: int,
    target_return_pct: float,
) -> dict:
    """Streamlitなどで使うバックテスト結果JSONを作成する。"""
    completed = records[records["検証状態"].isin(["成功", "未到達"])]
    successful = completed[completed["検証状態"] == "成功"]
    success_rate = (
        (len(successful) / len(completed)) * 100
        if not completed.empty
        else None
    )

    return {
        "作成日時UTC": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "検証条件": {
            "目標上昇率(%)": target_return_pct,
            "確認期間(取引日)": lookahead_days,
            "価格条件": "CSVに記録された終値が、判定時終値の目標上昇率以上に到達",
            "注意事項": (
                "検証中は将来の取引日数が不足しているため、"
                "途中で2%へ到達していても成功率の分母・分子に含めません。"
                "旧CSVに取引日がない場合は、"
                "CSV出力日を暫定的な取引日として扱います。"
            ),
        },
        "データ概要": {
            "CSVファイル数": csv_file_count,
            "ユニーク取引日数": int(history["取引日"].nunique())
            if not history.empty
            else 0,
            "最初の取引日": history["取引日"].min().strftime("%Y-%m-%d")
            if not history.empty
            else None,
            "最新取引日": history["取引日"].max().strftime("%Y-%m-%d")
            if not history.empty
            else None,
            "銘柄数": int(history["銘柄コード"].nunique())
            if not history.empty
            else 0,
        },
        "全体集計": {
            "候補件数": int(len(records)),
            "検証完了件数": int(len(completed)),
            "成功件数": int(len(successful)),
            "未到達件数": int(len(completed) - len(successful)),
            "検証中件数": int((records["検証状態"] == "検証中").sum())
            if not records.empty
            else 0,
            "成功率(%)": round(success_rate, 2)
            if success_rate is not None
            else None,
        },
        "スコア別集計": summarize_records(records, "スコア帯"),
        "判定別集計": summarize_records(records, "判定"),
        "銘柄別集計": summarize_records(records, "銘柄コード"),
        "取引別結果": convert_records_for_json(records),
    }


def write_summary(summary: dict, report_path: Path) -> None:
    """バックテスト結果をUTF-8のJSONで保存する。"""
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("w", encoding="utf-8") as file:
        json.dump(summary, file, ensure_ascii=False, indent=2)
        file.write("\n")


def main() -> None:
    """CSV読込からレポート保存までを実行する。"""
    arguments = parse_arguments()
    if arguments.lookahead_days <= 0:
        raise ValueError("--lookahead-days は1以上を指定してください。")
    if arguments.target_return_pct <= 0:
        raise ValueError("--target-return-pct は0より大きい値を指定してください。")

    history, csv_file_count = load_history(DATA_DIRECTORY)
    if history.empty:
        raise RuntimeError("検証できる日次CSVが data ディレクトリにありません。")

    records = create_trade_records(
        history=history,
        lookahead_days=arguments.lookahead_days,
        target_return_pct=arguments.target_return_pct,
    )
    summary = create_summary(
        history=history,
        records=records,
        csv_file_count=csv_file_count,
        lookahead_days=arguments.lookahead_days,
        target_return_pct=arguments.target_return_pct,
    )
    write_summary(summary, REPORT_PATH)

    overall = summary["全体集計"]
    print(f"バックテスト結果を保存しました: {REPORT_PATH}")
    print(
        "候補件数: {candidates}, 検証完了: {completed}, 成功: {success}, 成功率: {rate}".format(
            candidates=overall["候補件数"],
            completed=overall["検証完了件数"],
            success=overall["成功件数"],
            rate=overall["成功率(%)"],
        )
    )


if __name__ == "__main__":
    main()
