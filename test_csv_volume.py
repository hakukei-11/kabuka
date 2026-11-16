# test_csv_volume.py

import csv
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

import analysis_engine as engine
import candidate_tracker
import export_data
from test_csv_ohlc import ANALYSIS_AT, make_history


class CsvVolumeTests(unittest.TestCase):
    def export_frames(self, frames: dict[str, pd.DataFrame]) -> tuple[bytes, list[dict]]:
        """株価取得・通知を模擬し、実際のCSV保存先は一時フォルダーに限定する。"""
        original_to_csv = pd.DataFrame.to_csv
        with tempfile.TemporaryDirectory(prefix="kabuka-volume-test-") as temporary:
            output = Path(temporary) / "data_20260914.csv"

            def write_csv(frame, path, **kwargs):
                self.assertEqual(Path(path).name, output.name)
                self.assertEqual(str(frame["出来高"].dtype), "Int64")
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
            rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
            return raw, rows

    def test_volume_uses_same_confirmed_session_without_changing_input(self):
        for ticker, date in [("4519.T", "2026-09-14"), ("MSFT", "2026-09-11")]:
            with self.subTest(ticker=ticker):
                frame = make_history(ticker)
                frame.loc[date, "Volume"] = 1234567
                if ticker == "MSFT":
                    frame.loc["2026-09-14", "Volume"] = 999999999
                original = frame.copy(deep=True)
                result, _ = engine.analyze_dataframe(frame, ticker, ticker, ANALYSIS_AT)
                self.assertEqual(result["取引日"], date)
                self.assertEqual(result["出来高"], 1234567)
                self.assertIsInstance(result["出来高"], int)
                pd.testing.assert_frame_equal(frame, original)

    def test_missing_volume_is_not_forward_filled(self):
        frame = make_history("MSFT")
        frame["Volume"] = frame["Volume"].astype(float)
        frame.loc["2026-09-11", "Volume"] = float("nan")
        result, _ = engine.analyze_dataframe(frame, "MSFT", "Microsoft", ANALYSIS_AT)
        self.assertIsNone(result["出来高"])

    def test_missing_volume_column_is_allowed(self):
        frame = make_history("MSFT").drop(columns=["Volume"])
        result, _ = engine.analyze_dataframe(frame, "MSFT", "Microsoft", ANALYSIS_AT)
        self.assertEqual(result["取引日"], "2026-09-11")
        self.assertIsNone(result["出来高"])

    def test_volume_does_not_change_indicators_or_score_and_zero_is_preserved(self):
        frame = make_history("MSFT")
        expected, _ = engine.analyze_dataframe(frame, "MSFT", "Microsoft", ANALYSIS_AT)
        frame.loc["2026-09-11", "Volume"] = 0
        actual, _ = engine.analyze_dataframe(frame, "MSFT", "Microsoft", ANALYSIS_AT)
        self.assertEqual(actual["出来高"], 0)
        expected.pop("出来高")
        actual.pop("出来高")
        self.assertEqual(actual, expected)

    def test_missing_close_keeps_volume_aligned_with_last_valid_close(self):
        frame = make_history("MSFT")
        frame.loc["2026-09-10", "Volume"] = 24680
        frame.loc["2026-09-11", "Close"] = float("nan")
        frame.loc["2026-09-11", "Volume"] = 999999
        result, _ = engine.analyze_dataframe(frame, "MSFT", "Microsoft", ANALYSIS_AT)
        self.assertEqual(result["取引日"], "2026-09-10")
        self.assertEqual(result["出来高"], 24680)

    def test_export_preserves_integer_zero_and_missing_volume_with_utf8_bom(self):
        frames = {code: make_history(code) for code in ["4519.T", "MSFT", "AAPL", "NVDA"]}
        frames["4519.T"].loc["2026-09-14", "Volume"] = 5000000123
        frames["MSFT"].loc["2026-09-11", "Volume"] = 0
        frames["AAPL"]["Volume"] = frames["AAPL"]["Volume"].astype(float)
        frames["AAPL"].loc["2026-09-11", "Volume"] = float("nan")
        frames["NVDA"] = frames["NVDA"].drop(columns=["Volume"])
        raw, rows = self.export_frames(frames)
        self.assertEqual(raw[:3], b"\xef\xbb\xbf")
        self.assertEqual(list(rows[0])[4:9], ["始値", "高値", "安値", "終値", "出来高"])
        self.assertEqual(
            {row["銘柄コード"]: row["出来高"] for row in rows},
            {"4519.T": "5000000123", "MSFT": "0", "AAPL": "", "NVDA": ""},
        )

    def test_export_all_missing_volume_stays_blank(self):
        frames = {"MSFT": make_history("MSFT").drop(columns=["Volume"])}
        _, rows = self.export_frames(frames)
        self.assertEqual(rows[0]["出来高"], "")

    def test_legacy_csv_without_volume_is_still_readable(self):
        result, _ = engine.analyze_dataframe(make_history("MSFT"), "MSFT", "Microsoft", ANALYSIS_AT)
        legacy = pd.DataFrame([result]).drop(columns=["出来高"])
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
