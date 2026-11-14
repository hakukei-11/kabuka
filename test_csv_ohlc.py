# test_csv_ohlc.py

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

import analysis_engine as engine
import candidate_tracker
import export_data

ANALYSIS_AT = "2026-09-14 22:35:03"
PRICE_COLUMNS = ["始値", "高値", "安値"]
EXPECTED_PRICES = {"始値": 102.2, "高値": 104.0, "安値": 101.1, "終値": 102.7}


def make_history(ticker: str) -> pd.DataFrame:
    calendar = engine.get_market_calendar("JPX" if ticker.endswith(".T") else "NYSE")
    dates = calendar.schedule("2026-07-01", "2026-09-14").index
    closes = [100 + i * 0.2 + (i % 3) * 0.1 for i in range(len(dates))]
    frame = pd.DataFrame(
        {
            "Open": [value - 0.3 for value in closes],
            "High": [value + 1 for value in closes],
            "Low": [value - 1 for value in closes],
            "Close": closes,
            "Volume": 1000,
        },
        index=dates,
    )
    confirmed_date = "2026-09-14" if ticker.endswith(".T") else "2026-09-11"
    frame.loc[confirmed_date, ["Open", "High", "Low", "Close"]] = [
        102.234, 103.987, 101.123, 102.749
    ]
    if not ticker.endswith(".T"):
        frame.loc[dates[-1], ["Open", "High", "Low", "Close"]] = [
            9000, 10000, 8000, 9500
        ]
    return frame


class CsvOhlcTests(unittest.TestCase):
    def test_prices_come_from_same_confirmed_session(self):
        for ticker, expected_date in [("4519.T", "2026-09-14"), ("MSFT", "2026-09-11")]:
            with self.subTest(ticker=ticker):
                frame = make_history(ticker)
                result, _ = engine.analyze_dataframe(frame, ticker, ticker, ANALYSIS_AT)
                self.assertEqual(result["取引日"], expected_date)
                for name, expected in EXPECTED_PRICES.items():
                    self.assertEqual(result[name], expected)
                self.assertNotEqual(result["高値"], result["20日高値"])

    def test_missing_ohlc_is_not_forward_filled_for_storage(self):
        frame = make_history("MSFT")
        frame.loc["2026-09-11", ["Open", "High", "Low"]] = float("nan")
        result, _ = engine.analyze_dataframe(frame, "MSFT", "Microsoft", ANALYSIS_AT)
        self.assertEqual(result["取引日"], "2026-09-11")
        for name in PRICE_COLUMNS:
            self.assertIsNone(result[name])
        csv_text = pd.DataFrame([result]).to_csv(index=False)
        restored = pd.read_csv(io.StringIO(csv_text))
        self.assertTrue(restored[PRICE_COLUMNS].isna().all().all())

    def test_export_writes_daily_ohlc_columns_with_utf8_bom(self):
        frames = {ticker: make_history(ticker) for ticker in ["4519.T", "MSFT"]}
        original_to_csv = pd.DataFrame.to_csv
        with tempfile.TemporaryDirectory(prefix="kabuka-ohlc-test-") as temporary:
            output = Path(temporary) / "data_20260914.csv"

            def write_csv(frame, path, **kwargs):
                self.assertEqual(Path(path).name, output.name)
                return original_to_csv(frame, output, **kwargs)

            with patch.object(engine.yf, "Ticker") as ticker, patch.object(
                export_data, "TICKERS", {"4519.T": "中外製薬", "MSFT": "Microsoft"}
            ), patch.object(
                export_data, "get_analysis_executed_at", return_value=ANALYSIS_AT
            ), patch.object(export_data.os, "makedirs"), patch.object(
                pd.DataFrame, "to_csv", autospec=True, side_effect=write_csv
            ), patch.object(export_data, "send_line"):
                ticker.side_effect = lambda code: type(
                    "Quote", (), {"history": lambda self, **kwargs: frames[code]}
                )()
                export_data.main()

            self.assertEqual(output.read_bytes()[:3], b"\xef\xbb\xbf")
            restored = pd.read_csv(output, encoding="utf-8-sig")
            self.assertEqual(len(restored), 2)
            self.assertEqual(
                restored.columns[4:8].tolist(), ["始値", "高値", "安値", "終値"]
            )
            for _, row in restored.iterrows():
                expected_date = "2026-09-14" if row["銘柄コード"].endswith(".T") else "2026-09-11"
                self.assertEqual(row["取引日"], expected_date)
                for name, expected in EXPECTED_PRICES.items():
                    self.assertEqual(row[name], expected)
                expected, _ = engine.analyze_dataframe(
                    frames[row["銘柄コード"]], row["銘柄コード"], row["銘柄名"], ANALYSIS_AT
                )
                for name in ["RSI", "MACD", "Signal", "判定", "反発確度スコア"]:
                    self.assertEqual(row[name], expected[name])

    def test_legacy_csv_without_ohlc_is_still_readable(self):
        result, _ = engine.analyze_dataframe(make_history("MSFT"), "MSFT", "Microsoft", ANALYSIS_AT)
        legacy = pd.DataFrame([result]).drop(columns=PRICE_COLUMNS)
        legacy["反発確度スコア"] = 60
        source = Path("data/2026/09/data_20260914.csv")
        records = candidate_tracker.make_candidate_records(legacy, source)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["終値"], EXPECTED_PRICES["終値"])
        with patch.object(candidate_tracker, "get_daily_csv_paths", return_value=[source]), patch.object(
            candidate_tracker, "read_csv", return_value=legacy
        ):
            history = candidate_tracker.load_close_history()
        self.assertEqual(history["MSFT"], [(pd.Timestamp("2026-09-11"), EXPECTED_PRICES["終値"])])


if __name__ == "__main__":
    unittest.main()

