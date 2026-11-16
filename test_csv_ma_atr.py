# test_csv_ma_atr.py

import csv
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

import analysis_engine as engine
import candidate_tracker
import export_data
from indicators import calc_atr
from test_csv_ohlc import ANALYSIS_AT, make_history

NEW_COLUMNS = ["5MA", "10MA", "ATR14"]
# 追加前の共通分析結果を固定し、既存列の変更を検出する。
LEGACY_RESULTS = json.loads(r'''
{
  "4519.T": {
    "分析実行日時": "2026-09-14 22:35:03",
    "取引日": "2026-09-14",
    "銘柄コード": "4519.T",
    "銘柄名": "4519.T",
    "始値": 102.2,
    "高値": 104,
    "安値": 101.1,
    "終値": 102.7,
    "出来高": 1000,
    "前日比": -7.5,
    "前日比率(%)": -6.76,
    "RSI": 26.6,
    "MACD": 0.755,
    "Signal": 1.212,
    "25MA": 107.6,
    "20日高値": 111.2,
    "20日安値": 101.1,
    "25MAタッチ": false,
    "20日安値タッチ": false,
    "陽線": true,
    "終値位置(%)": 56.8,
    "反発初動": false,
    "判定": "RSI 26.6（売られ過ぎ） / MACDデッドクロス（下落トレンド寄り） / 総合スコア 20点（反発余地あり）",
    "反発確度スコア": 20
  },
  "MSFT": {
    "分析実行日時": "2026-09-14 22:35:03",
    "取引日": "2026-09-11",
    "銘柄コード": "MSFT",
    "銘柄名": "MSFT",
    "始値": 102.2,
    "高値": 104,
    "安値": 101.1,
    "終値": 102.7,
    "出来高": 1000,
    "前日比": -7.2,
    "前日比率(%)": -6.51,
    "RSI": 27.4,
    "MACD": 0.761,
    "Signal": 1.207,
    "25MA": 107.4,
    "20日高値": 110.9,
    "20日安値": 101.1,
    "25MAタッチ": false,
    "20日安値タッチ": false,
    "陽線": true,
    "終値位置(%)": 56.8,
    "反発初動": false,
    "判定": "RSI 27.4（売られ過ぎ） / MACDデッドクロス（下落トレンド寄り） / 総合スコア 20点（反発余地あり）",
    "反発確度スコア": 20
  }
}
''')


class AtrTests(unittest.TestCase):
    def test_true_range_includes_upward_and_downward_gaps(self):
        index = pd.date_range("2026-09-01", periods=5)
        high = pd.Series([10, 13, 12, 7, 9], index=index, dtype=float)
        low = pd.Series([8, 11, 9, 5, 8], index=index, dtype=float)
        close = pd.Series([9, 12, 10, 6, 8.5], index=index, dtype=float)
        actual = calc_atr(high, low, close, period=3)
        expected = pd.Series(
            [float("nan"), float("nan"), 3, 11 / 3, 31 / 9],
            index=index, name="ATR3",
        )
        pd.testing.assert_series_equal(actual, expected)

    def test_wilder_seed_and_recursive_smoothing_are_not_a_rolling_average(self):
        close = pd.Series([100.0] * 16)
        high = pd.Series([101.0] * 14 + [105.0, 101.0])
        low = pd.Series([99.0] * 14 + [95.0, 99.0])
        actual = calc_atr(high, low, close)
        self.assertTrue(actual.iloc[:13].isna().all())
        self.assertEqual(actual.iloc[13], 2)
        self.assertAlmostEqual(actual.iloc[14], 36 / 14)
        self.assertAlmostEqual(actual.iloc[15], ((36 / 14) * 13 + 2) / 14)
        self.assertNotAlmostEqual(actual.iloc[15], 36 / 14)

    def test_missing_high_or_low_resets_without_forward_filling(self):
        for missing_column in ["High", "Low"]:
            with self.subTest(column=missing_column):
                prices = pd.DataFrame({"High": [11.0] * 8, "Low": [9.0] * 8, "Close": [10.0] * 8})
                prices.loc[3, missing_column] = float("nan")
                actual = calc_atr(prices["High"], prices["Low"], prices["Close"], period=3)
                self.assertEqual(actual.iloc[2], 2)
                self.assertTrue(actual.iloc[3:6].isna().all())
                self.assertEqual(actual.iloc[6], 2)

    def test_missing_close_does_not_connect_nonadjacent_sessions(self):
        high = pd.Series([11.0] * 9)
        low = pd.Series([9.0] * 9)
        close = pd.Series([10.0] * 9)
        close.iloc[3] = float("nan")
        actual = calc_atr(high, low, close, period=3)
        self.assertEqual(actual.iloc[2], 2)
        self.assertTrue(actual.iloc[3:7].isna().all())
        self.assertEqual(actual.iloc[7], 2)

    def test_empty_and_insufficient_history_have_no_invented_values(self):
        empty = pd.Series(dtype=float)
        self.assertTrue(calc_atr(empty, empty, empty).empty)
        close = pd.Series([10.0] * 13)
        self.assertTrue(calc_atr(close + 1, close - 1, close).isna().all())

    def test_flat_prices_produce_zero_atr(self):
        close = pd.Series([10.0] * 16)
        actual = calc_atr(close, close, close)
        self.assertTrue(actual.iloc[:13].isna().all())
        self.assertTrue((actual.iloc[13:] == 0).all())

    def test_invalid_period_is_rejected(self):
        close = pd.Series([10.0] * 16)
        for period in [0, -1, 1.5, True]:
            with self.subTest(period=period), self.assertRaises(ValueError):
                calc_atr(close, close, close, period=period)

    def test_invalid_range_and_infinite_prices_are_not_valid_true_ranges(self):
        for value in [float("inf"), float("-inf"), float("nan"), 8.0]:
            with self.subTest(high=value):
                high = pd.Series([11.0] * 20)
                low = pd.Series([9.0] * 20)
                close = pd.Series([10.0] * 20)
                high.iloc[-1] = value
                actual = calc_atr(high, low, close)
                self.assertTrue(pd.isna(actual.iloc[-1]))


class CsvMaAtrTests(unittest.TestCase):
    def test_moving_averages_use_confirmed_adjusted_closes(self):
        for ticker, date in [("4519.T", "2026-09-14"), ("MSFT", "2026-09-11")]:
            with self.subTest(ticker=ticker):
                frame = make_history(ticker)
                original = frame.copy(deep=True)
                result, chart = engine.analyze_dataframe(frame, ticker, ticker, ANALYSIS_AT)
                closes = frame.loc[:date, "Close"].tolist()
                self.assertEqual(result["取引日"], date)
                self.assertEqual(result["5MA"], round(sum(closes[-5:]) / 5, 3))
                self.assertEqual(result["10MA"], round(sum(closes[-10:]) / 10, 3))
                self.assertEqual(result["ATR14"], round(float(chart["ATR14"].iloc[-1]), 3))
                self.assertTrue(result["ATR14"] >= 0)
                pd.testing.assert_frame_equal(frame, original)

    def test_all_legacy_result_fields_are_unchanged(self):
        for ticker, expected in LEGACY_RESULTS.items():
            with self.subTest(ticker=ticker):
                actual, _ = engine.analyze_dataframe(make_history(ticker), ticker, ticker, ANALYSIS_AT)
                legacy = {key: value for key, value in actual.items() if key not in NEW_COLUMNS}
                self.assertEqual(legacy, expected)
                self.assertEqual(set(actual) - set(expected), set(NEW_COLUMNS))

    def test_missing_high_low_keeps_atr_blank_without_discarding_analysis(self):
        frame = make_history("MSFT")
        frame.loc["2026-09-11", ["High", "Low"]] = float("nan")
        result, _ = engine.analyze_dataframe(frame, "MSFT", "Microsoft", ANALYSIS_AT)
        self.assertIsNotNone(result)
        self.assertEqual(result["取引日"], "2026-09-11")
        self.assertIsNone(result["ATR14"])
        self.assertIsNotNone(result["5MA"])
        self.assertIsNotNone(result["10MA"])

    def test_atr_uses_raw_missing_close_before_existing_cleanup(self):
        frame = make_history("MSFT")
        frame.loc["2026-09-10", "Close"] = float("nan")
        result, _ = engine.analyze_dataframe(frame, "MSFT", "Microsoft", ANALYSIS_AT)
        self.assertEqual(result["取引日"], "2026-09-11")
        self.assertIsNone(result["ATR14"])

    def test_unfinished_candle_cannot_change_new_indicators(self):
        frame = make_history("MSFT")
        expected, expected_chart = engine.analyze_dataframe(frame.iloc[:-1], "MSFT", "Microsoft", ANALYSIS_AT)
        actual, actual_chart = engine.analyze_dataframe(frame, "MSFT", "Microsoft", ANALYSIS_AT)
        self.assertEqual(actual, expected)
        pd.testing.assert_frame_equal(actual_chart[NEW_COLUMNS], expected_chart[NEW_COLUMNS])

    def test_export_writes_new_columns_and_missing_atr_as_blank(self):
        frames = {ticker: make_history(ticker) for ticker in ["4519.T", "MSFT", "AAPL"]}
        frames["AAPL"].loc["2026-09-11", ["High", "Low"]] = float("nan")
        original_to_csv = pd.DataFrame.to_csv
        with tempfile.TemporaryDirectory(prefix="kabuka-ma-atr-test-") as temporary:
            output = Path(temporary) / "data_20260914.csv"

            def write_csv(frame, path, **kwargs):
                self.assertEqual(Path(path).name, output.name)
                return original_to_csv(frame, output, **kwargs)

            with patch.object(engine.yf, "Ticker") as ticker, patch.object(
                export_data, "TICKERS", {code: code for code in frames}
            ), patch.object(
                export_data, "get_analysis_executed_at", return_value=ANALYSIS_AT
            ), patch.object(export_data.os, "makedirs"), patch.object(
                pd.DataFrame, "to_csv", autospec=True, side_effect=write_csv
            ), patch.object(export_data, "send_line"):
                ticker.side_effect = lambda code: type(
                    "Quote", (), {"history": lambda self, **kwargs: frames[code]}
                )()
                export_data.main()

            raw = output.read_bytes()
            self.assertEqual(raw[:3], b"\xef\xbb\xbf")
            rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
            self.assertEqual(len(rows), 3)
            headers = list(rows[0])
            start = headers.index("5MA")
            self.assertEqual(headers[start:start + 4], ["5MA", "10MA", "25MA", "ATR14"])
            for row in rows:
                code = row["銘柄コード"]
                expected, _ = engine.analyze_dataframe(frames[code], code, code, ANALYSIS_AT)
                for column in NEW_COLUMNS:
                    if expected[column] is None:
                        self.assertEqual(row[column], "")
                    else:
                        self.assertEqual(float(row[column]), expected[column])

    def test_legacy_csv_without_new_indicators_is_still_readable(self):
        result, _ = engine.analyze_dataframe(make_history("MSFT"), "MSFT", "Microsoft", ANALYSIS_AT)
        legacy = pd.DataFrame([result]).drop(columns=NEW_COLUMNS)
        legacy["反発確度スコア"] = 60
        source = Path("data/2026/09/data_20260914.csv")
        records = candidate_tracker.make_candidate_records(legacy, source)
        self.assertEqual(len(records), 1)
        with patch.object(candidate_tracker, "get_daily_csv_paths", return_value=[source]), patch.object(
            candidate_tracker, "read_csv", return_value=legacy
        ):
            history = candidate_tracker.load_close_history()
        self.assertEqual(history["MSFT"], [(pd.Timestamp("2026-09-11"), result["終値"])])


if __name__ == "__main__":
    unittest.main()

