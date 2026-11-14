# test_confirmed_close.py

import math
import unittest
from unittest.mock import patch

import pandas as pd

import analysis_engine as engine


def make_prices(index: pd.DatetimeIndex) -> pd.DataFrame:
    closes = [100 + i * 0.2 + math.sin(i) for i in range(len(index))]
    return pd.DataFrame(
        {
            "Open": [close - 0.3 for close in closes],
            "High": [close + 1 for close in closes],
            "Low": [close - 1 for close in closes],
            "Close": closes,
            "Volume": 1000,
        },
        index=index,
    )


class ConfirmedCloseTests(unittest.TestCase):
    def test_close_and_wait_boundaries(self):
        cases = [
            ("MSFT", "2026-09-14", "2026-09-15 05:29:59", "2026-09-15 05:30:00"),
            ("MSFT", "2026-01-05", "2026-01-06 06:29:59", "2026-01-06 06:30:00"),
            ("MSFT", "2026-11-27", "2026-11-28 03:29:59", "2026-11-28 03:30:00"),
            ("4519.T", "2024-11-01", "2024-11-01 15:29:59", "2024-11-01 15:30:00"),
            ("4519.T", "2024-11-05", "2024-11-05 15:59:59", "2024-11-05 16:00:00"),
            ("4519.T", "2026-10-06", "2026-10-06 15:59:59", "2026-10-06 16:00:00"),
        ]
        for ticker, date, before, after in cases:
            with self.subTest(ticker=ticker, date=date):
                frame = make_prices(pd.DatetimeIndex([date]))
                self.assertTrue(engine.filter_confirmed_daily_prices(frame, ticker, before).empty)
                self.assertEqual(len(engine.filter_confirmed_daily_prices(frame, ticker, after)), 1)

    def test_us_intraday_and_japan_lunch_are_excluded(self):
        for ticker, date, at in [
            ("MSFT", "2026-09-14", "2026-09-14 22:35:03"),
            ("4519.T", "2026-10-06", "2026-10-06 12:00:00"),
        ]:
            with self.subTest(ticker=ticker):
                frame = make_prices(pd.DatetimeIndex([date]))
                self.assertTrue(engine.filter_confirmed_daily_prices(frame, ticker, at).empty)

    def test_non_sessions_and_future_rows_are_excluded(self):
        for ticker, dates, at, expected in [
            (
                "4519.T",
                ["2026-09-18", "2026-09-19", "2026-09-21", "2026-09-22", "2026-09-23", "2026-09-24"],
                "2026-09-23 18:00:00",
                ["2026-09-18"],
            ),
            (
                "MSFT",
                ["2026-09-04", "2026-09-05", "2026-09-07", "2026-09-08"],
                "2026-09-08 07:00:00",
                ["2026-09-04"],
            ),
        ]:
            with self.subTest(ticker=ticker):
                frame = make_prices(pd.DatetimeIndex(dates))
                result = engine.filter_confirmed_daily_prices(frame, ticker, at)
                self.assertEqual(result.index.strftime("%Y-%m-%d").tolist(), expected)

    def test_naive_local_and_utc_indices_use_market_trade_date(self):
        for ticker, timezone in [("4519.T", "Asia/Tokyo"), ("MSFT", "America/New_York")]:
            with self.subTest(ticker=ticker):
                index = pd.DatetimeIndex(["2026-10-06"], name="Date")
                reference = make_prices(index)
                local = reference.copy()
                local.index = index.tz_localize(timezone)
                utc = local.copy()
                utc.index = local.index.tz_convert("UTC")
                for frame in [reference, local, utc]:
                    result = engine.filter_confirmed_daily_prices(frame, ticker, "2026-10-07 08:00:00")
                    pd.testing.assert_frame_equal(result, reference)
                    self.assertEqual(engine.get_trade_date(result), "2026-10-06")

    def test_timezone_aware_reference_matches_jst_reference(self):
        frame = make_prices(pd.DatetimeIndex(["2026-10-06"]))
        jst = engine.filter_confirmed_daily_prices(frame, "MSFT", "2026-10-07 05:30:00")
        utc = engine.filter_confirmed_daily_prices(frame, "MSFT", "2026-10-06T20:30:00Z")
        pd.testing.assert_frame_equal(jst, utc)

    def test_invalid_reference_fails_closed(self):
        frame = make_prices(pd.DatetimeIndex(["2026-10-06"]))
        with self.assertRaises(ValueError):
            engine.filter_confirmed_daily_prices(frame, "MSFT", "NaT")

    def make_intraday_history(self):
        dates = engine.get_market_calendar("NYSE").schedule("2026-07-01", "2026-09-14").index
        frame = make_prices(dates)
        frame.loc[dates[-1], ["Open", "High", "Low", "Close"]] = [9000, 10000, 8000, 9500]
        return frame

    def test_unfinished_quote_cannot_change_indicators_or_score(self):
        frame = self.make_intraday_history()
        original = frame.copy(deep=True)
        at = "2026-09-14 22:35:03"
        expected, expected_chart = engine.analyze_dataframe(frame.iloc[:-1], "MSFT", "Microsoft", at)
        actual, actual_chart = engine.analyze_dataframe(frame, "MSFT", "Microsoft", at)
        self.assertEqual(actual, expected)
        pd.testing.assert_frame_equal(actual_chart, expected_chart)
        pd.testing.assert_frame_equal(frame, original)
        self.assertEqual(actual["取引日"], "2026-09-11")

    def test_too_short_history_after_filter_and_empty_input(self):
        frame = self.make_intraday_history().tail(26)
        self.assertEqual(engine.analyze_dataframe(frame, "MSFT", "Microsoft", "2026-09-14 22:35:03"), (None, None))
        self.assertEqual(engine.analyze_dataframe(frame.iloc[0:0], "MSFT", "Microsoft"), (None, None))
        self.assertEqual(engine.analyze_dataframe(None, "MSFT", "Microsoft"), (None, None))

    def test_missing_latest_session_does_not_invent_a_quote(self):
        frame = self.make_intraday_history().iloc[:-2]
        result, _ = engine.analyze_dataframe(frame, "MSFT", "Microsoft", "2026-09-15 07:00:00")
        self.assertEqual(result["取引日"], "2026-09-10")

    def test_historical_indicator_preparation_is_unchanged(self):
        frame = self.make_intraday_history()
        result = engine.prepare_dataframe(frame)
        self.assertEqual(len(result), len(frame))
        self.assertEqual(float(result["Close"].iloc[-1]), 9500)

    def test_single_download_uses_adjusted_daily_prices(self):
        frame = self.make_intraday_history()
        at = "2026-09-14 22:35:03"
        expected, expected_chart = engine.analyze_dataframe(frame, "MSFT", "Microsoft", at)
        with patch.object(engine.yf, "Ticker") as ticker:
            ticker.return_value.history.return_value = frame
            actual, actual_chart = engine.analyze_ticker("MSFT", "Microsoft", analysis_executed_at=at)
        ticker.return_value.history.assert_called_once_with(period="6mo", interval="1d", auto_adjust=True)
        self.assertEqual(actual, expected)
        pd.testing.assert_frame_equal(actual_chart, expected_chart)

    def test_csv_and_update_status_match_shared_analysis_without_side_effects(self):
        import export_data
        import update_checker

        frame = self.make_intraday_history()
        at = "2026-09-14 22:35:03"
        expected, _ = engine.analyze_dataframe(frame, "MSFT", "Microsoft", at)
        with patch.object(engine.yf, "Ticker") as ticker, patch.object(engine, "get_analysis_executed_at", return_value=at):
            ticker.return_value.history.return_value = frame
            with patch.object(export_data, "TICKERS", {"MSFT": "Microsoft"}), patch.object(
                export_data, "get_analysis_executed_at", return_value=at
            ), patch.object(export_data.os, "makedirs"), patch.object(
                pd.DataFrame, "to_csv", autospec=True
            ) as save_csv, patch.object(export_data, "send_line") as notify:
                export_data.main()
                csv_row = save_csv.call_args.args[0].iloc[0].to_dict()
                self.assertEqual(csv_row, expected)
                self.assertEqual(save_csv.call_args.kwargs["encoding"], "utf-8-sig")
                self.assertIn(expected["取引日"], notify.call_args.args[0])

            with patch.object(update_checker, "TICKERS", {"MSFT": "Microsoft"}), patch.object(
                update_checker, "load_status", return_value={"MSFT": {"last_close": 0, "last_trade_date": "2026-07-01"}}
            ), patch.object(update_checker, "save_status") as save_status, patch.object(
                update_checker, "send_line"
            ) as notify:
                update_checker.main()
                status = save_status.call_args.args[0]["MSFT"]
                self.assertEqual(status["last_trade_date"], expected["取引日"])
                self.assertEqual(status["last_close"], expected["終値"])
                self.assertTrue(status["last_checked_at"])
                if expected["反発確度スコア"] >= update_checker.SCORE_NOTIFICATION_THRESHOLD:
                    self.assertIn(expected["判定"], notify.call_args.args[0])


if __name__ == "__main__":
    unittest.main()

