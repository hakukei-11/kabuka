# app.py
import json
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st
import yfinance as yf

from analysis_engine import analyze_dataframe, get_analysis_executed_at
from chart import plot_chart
from tickers import TICKERS

font_path = "./fonts/ipaexg.ttf"
fm.fontManager.addfont(font_path)
matplotlib.rc("font", family="IPAexGothic")
matplotlib.rcParams["axes.unicode_minus"] = False

SCORE_DISPLAY_THRESHOLD = 50
BACKTEST_REPORT_PATH = Path("reports/backtest_summary.json")
HISTORICAL_BACKTEST_REPORT_PATH = Path("reports/historical_backtest_summary.json")
RISK_BACKTEST_REPORT_PATH = Path("reports/risk_backtest_summary.json")

st.set_page_config(
    page_title="寄り付き天底狙いスクリーナー",
    layout="wide",
)

st.title("📊 寄り付き天底狙いスクリーナー")
st.caption("RSI・MACD・移動平均・ボックス圏を用いた反発候補スクリーニング")


def show_update_status():
    """GitHub Actionsが更新する終値確認結果を表示する。"""
    st.header("📅 終値更新状況（GitHub Actions）")

    try:
        with open("update_status.json", "r", encoding="utf-8") as file:
            update_status = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        update_status = {}

    status_columns = st.columns(2)

    for column, ticker, label in [
        (status_columns[0], "7203.T", "日本株：トヨタ自動車"),
        (status_columns[1], "AAPL", "米国株：Apple"),
    ]:
        with column:
            info = update_status.get(ticker)

            if not info:
                st.info(f"{label}\n\nデータなし")
                continue

            trade_date = info.get("last_trade_date", "不明")
            update_time = info.get("last_update_time", "未更新")

            if info.get("updated"):
                st.success(
                    f"{label}\n\n"
                    f"終値更新を検出\n\n"
                    f"取引日: {trade_date}\n\n"
                    f"検出時刻: {update_time}"
                )
            else:
                st.info(
                    f"{label}\n\n"
                    f"最新取引日: {trade_date}\n\n"
                    f"最終確認時刻: {info.get('last_checked_at', '不明')}"
                )


@st.cache_data(ttl=300, show_spinner=False)
def load_backtest_summary() -> dict | None:
    """backtest.pyが出力した集計JSONを読み込む。"""
    try:
        with BACKTEST_REPORT_PATH.open("r", encoding="utf-8") as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


@st.cache_data(ttl=300, show_spinner=False)
def load_historical_backtest_summary() -> dict | None:
    """historical_backtest.pyが出力した集計JSONを読み込む。"""
    try:
        with HISTORICAL_BACKTEST_REPORT_PATH.open("r", encoding="utf-8") as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


@st.cache_data(ttl=300, show_spinner=False)
def load_risk_backtest_summary() -> dict | None:
    """risk_backtest.pyが出力した集計JSONを読み込む。"""
    try:
        with RISK_BACKTEST_REPORT_PATH.open("r", encoding="utf-8") as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def format_percentage(value: float | None) -> str:
    """成功率などのパーセント表示を統一する。"""
    return f"{value:.2f}%" if value is not None else "検証中"


def format_price(value: float | None, currency: str) -> str:
    """株価を通貨に応じた表示用の文字列へ変換する。"""
    if value is None or pd.isna(value):
        return "データなし"

    if currency == "JPY":
        return f"¥{value:,.0f}"
    return f"${value:,.2f}"


@st.cache_data(ttl=86400, show_spinner=False)
def get_analyst_price_targets(ticker: str) -> dict | None:
    """Yahoo Finance経由でアナリスト予想株価を取得し、24時間キャッシュする。"""
    try:
        ticker_object = yf.Ticker(ticker)
        fetcher = getattr(ticker_object, "get_analyst_price_targets", None)
        targets = (
            fetcher()
            if callable(fetcher)
            else ticker_object.analyst_price_targets
        )
    except Exception:
        return None

    if not isinstance(targets, dict):
        return None

    result = {
        "current": pd.to_numeric(targets.get("current"), errors="coerce"),
        "low": pd.to_numeric(targets.get("low"), errors="coerce"),
        "high": pd.to_numeric(targets.get("high"), errors="coerce"),
        "mean": pd.to_numeric(targets.get("mean"), errors="coerce"),
        "median": pd.to_numeric(targets.get("median"), errors="coerce"),
        "取得日時UTC": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    if all(pd.isna(result[key]) for key in ["low", "high", "mean", "median"]):
        return None

    return result


def show_analyst_price_targets(
    ticker: str,
    name: str,
    latest_close: float,
) -> None:
    """選択銘柄のアナリスト予想株価を参考情報として表示する。"""
    st.subheader("🎯 アナリスト予想株価（参考）")
    targets = get_analyst_price_targets(ticker)

    if targets is None:
        st.info(
            f"{name}（{ticker}）のアナリスト予想株価は取得できませんでした。"
        )
        return

    currency = "JPY" if ticker.endswith(".T") else "USD"
    mean_target = targets["mean"]
    mean_upside = (
        ((mean_target - latest_close) / latest_close) * 100
        if pd.notna(mean_target) and latest_close > 0
        else None
    )

    metric_columns = st.columns(4)
    metric_columns[0].metric(
        "平均目標株価",
        format_price(mean_target, currency),
        format_percentage(mean_upside) if mean_upside is not None else None,
    )
    metric_columns[1].metric(
        "中央値",
        format_price(targets["median"], currency),
    )
    metric_columns[2].metric(
        "予想安値",
        format_price(targets["low"], currency),
    )
    metric_columns[3].metric(
        "予想高値",
        format_price(targets["high"], currency),
    )

    st.caption(
        f"基準終値: {format_price(latest_close, currency)} / "
        f"取得日時（UTC）: {targets['取得日時UTC']}"
    )
    st.caption(
        "Yahoo Finance経由のアナリスト予想集計値です。"
        "銘柄によって未提供・更新遅延があります。"
        "売買を推奨する情報ではありません。"
    )


def show_backtest_tab():
    """CSV履歴を利用した終値ベースの2%到達検証を表示する。"""
    st.header("📈 2%到達バックテスト")
    st.caption(
        "各CSVの終値を買値と仮定し、以後の取引日で終値が2%上昇したかを検証します。"
    )

    summary = load_backtest_summary()
    if summary is None:
        st.info(
            "バックテスト結果がまだありません。ターミナルで "
            "`python backtest.py` を実行してください。"
        )
        return

    conditions = summary.get("検証条件", {})
    data_overview = summary.get("データ概要", {})
    overall = summary.get("全体集計", {})

    st.caption(
        f"作成日時（UTC）: {summary.get('作成日時UTC', '不明')} / "
        f"対象期間: {data_overview.get('最初の取引日', '不明')} ～ "
        f"{data_overview.get('最新取引日', '不明')}"
    )
    st.info(
        f"条件: 終値が{conditions.get('目標上昇率(%)', 2)}%上昇するかを、"
        f"以後{conditions.get('確認期間(取引日)', 20)}取引日で確認します。"
    )

    metric_columns = st.columns(4)
    metric_columns[0].metric("候補件数", overall.get("候補件数", 0))
    metric_columns[1].metric("検証完了", overall.get("検証完了件数", 0))
    metric_columns[2].metric("2%到達", overall.get("成功件数", 0))
    metric_columns[3].metric("2%到達率", format_percentage(overall.get("成功率(%)")))

    if overall.get("検証完了件数", 0) == 0:
        st.warning(
            "20取引日先まで確認できる履歴がまだ不足しています。"
            "CSVが蓄積されると、検証完了件数と成功率が表示されます。"
        )

    st.subheader("スコア帯別の2%到達率")
    score_summary = pd.DataFrame(summary.get("スコア別集計", []))
    if score_summary.empty:
        st.info("集計できるスコアデータがありません。")
    else:
        st.dataframe(score_summary, use_container_width=True, hide_index=True)

    st.subheader("銘柄別の2%到達率")
    ticker_summary = pd.DataFrame(summary.get("銘柄別集計", []))
    if ticker_summary.empty:
        st.info("集計できる銘柄データがありません。")
    else:
        st.dataframe(ticker_summary, use_container_width=True, hide_index=True)

    st.subheader("取引別の検証結果")
    records = pd.DataFrame(summary.get("取引別結果", []))
    if records.empty:
        st.info("取引別の結果はまだありません。")
        return

    status_options = ["すべて"] + sorted(records["検証状態"].dropna().unique().tolist())
    selected_status = st.selectbox("検証状態で絞り込み", status_options)
    if selected_status != "すべて":
        records = records[records["検証状態"] == selected_status]

    display_columns = [
        "銘柄コード",
        "銘柄名",
        "取引日",
        "終値",
        "目標売値",
        "反発確度スコア",
        "スコア帯",
        "検証状態",
        "2%到達取引日",
        "到達日数",
        "最大上昇率(%)",
        "判定",
    ]
    st.dataframe(
        records.reindex(columns=display_columns),
        use_container_width=True,
        hide_index=True,
    )


def show_historical_backtest_tab():
    """過去日足で再計算したスコアの2%到達率を表示する。"""
    st.header("🕰️ 過去データ検証")
    summary = load_historical_backtest_summary()

    if summary is None:
        st.info(
            "履歴バックテスト結果がまだありません。ターミナルで "
            "`python historical_backtest.py` を実行してください。"
        )
        return

    conditions = summary.get("検証条件", {})
    overall = summary.get("全体集計", {})
    st.caption(f"作成日時（UTC）: {summary.get('作成日時UTC', '不明')}")
    st.info(
        f"条件: 過去{conditions.get('取得期間', '2y')}の調整済み終値を使い、"
        f"以後{conditions.get('確認期間(取引日)', 20)}取引日以内の"
        f"{conditions.get('目標上昇率(%)', 2)}%到達率を検証します。"
    )

    metric_columns = st.columns(4)
    metric_columns[0].metric("検証件数", overall.get("検証件数", 0))
    metric_columns[1].metric("成功件数", overall.get("成功件数", 0))
    metric_columns[2].metric("2%到達率", format_percentage(overall.get("成功率(%)")))
    metric_columns[3].metric("対象銘柄数", overall.get("対象銘柄数", 0))

    st.subheader("スコア帯別の2%到達率")
    score_summary = pd.DataFrame(summary.get("スコア別集計", []))
    st.dataframe(score_summary, use_container_width=True, hide_index=True)

    st.subheader("条件別の2%到達率")
    st.caption(
        "現行スコアを構成する各条件を個別に比較します。"
        "成功率だけでなく検証件数も確認してください。"
    )
    condition_summaries = summary.get("条件別集計", {})
    condition_columns = st.columns(2)
    for index, condition_name in enumerate(
        ["25MA条件", "20日安値条件", "RSI条件", "MACD条件"]
    ):
        with condition_columns[index % 2]:
            st.markdown(f"#### {condition_name}")
            condition_summary = pd.DataFrame(
                condition_summaries.get(condition_name, [])
            )
            if condition_summary.empty:
                st.info("集計データがありません。")
            else:
                st.dataframe(
                    condition_summary,
                    use_container_width=True,
                    hide_index=True,
                )

    st.subheader("時系列分割による再現性確認")
    time_split = summary.get("時系列分割検証", {})
    st.caption(
        f"前半70%と後半30%の分割日: {time_split.get('分割日', '不明')}。"
        "前半だけで良く、後半で再現しない条件は採用しません。"
    )
    strategy_summary = pd.DataFrame(time_split.get("戦略別集計", []))
    if strategy_summary.empty:
        st.info("時系列分割の集計データがありません。")
    else:
        st.dataframe(
            strategy_summary,
            use_container_width=True,
            hide_index=True,
        )

    st.subheader("銘柄別の2%到達率")
    ticker_summary = pd.DataFrame(summary.get("銘柄別集計", []))
    st.dataframe(ticker_summary, use_container_width=True, hide_index=True)
    st.caption(conditions.get("注意事項", ""))


def show_risk_backtest_tab():
    """利確到達と最大含み損を含むリスク検証を表示する。"""
    st.header("⚖️ リスク込み過去データ検証")
    summary = load_risk_backtest_summary()
    if summary is None:
        st.info("結果がまだありません。`python risk_backtest.py` を実行してください。")
        return
    conditions = summary.get("検証条件", {})
    st.info(
        f"条件: +{conditions.get('利確目標(%)', 2)}%到達、"
        f"{conditions.get('損失閾値(%)', [3, 5])}%下落、"
        f"{conditions.get('確認期間(取引日)', 20)}取引日を確認します。"
    )
    overall = pd.DataFrame(summary.get("全体集計", []))
    event_order = pd.DataFrame(summary.get("先後判定集計", []))
    ticker_summary = pd.DataFrame(summary.get("銘柄別集計", []))
    st.subheader("全銘柄の集計")
    st.dataframe(overall, use_container_width=True, hide_index=True)
    st.subheader("利確・損失ラインの先後判定")
    st.dataframe(event_order, use_container_width=True, hide_index=True)
    st.caption(
        "保守成功率は同日両方到達を失敗扱い、楽観成功率は成功扱いにした範囲です。"
    )
    st.subheader("銘柄別の集計")
    st.dataframe(ticker_summary, use_container_width=True, hide_index=True)
    st.caption("同一日に利確価格と損失価格の両方へ到達した順序は、日足だけでは判定できません。")


@st.cache_data(ttl=3600, show_spinner=False)
def analyze_all_tickers():
    """全対象銘柄を一括取得し、共通分析エンジンで評価する。"""
    ticker_list = list(TICKERS.keys())
    analysis_executed_at = get_analysis_executed_at()

    downloaded_data = yf.download(
        ticker_list,
        period="6mo",
        group_by="ticker",
        threads=True,
        auto_adjust=True,
        progress=False,
    )

    results = []
    chart_data = {}

    for ticker, name in TICKERS.items():
        try:
            ticker_df = downloaded_data[ticker].dropna(how="all")
        except (KeyError, TypeError):
            continue

        result, analyzed_df = analyze_dataframe(
            df=ticker_df,
            ticker=ticker,
            name=name,
            analysis_executed_at=analysis_executed_at,
        )

        if result is None or analyzed_df is None:
            continue

        chart_data[ticker] = analyzed_df

        if result["反発確度スコア"] >= SCORE_DISPLAY_THRESHOLD:
            results.append(result)

    return results, chart_data


def show_stock_tab(
    results_df: pd.DataFrame,
    chart_data: dict,
    tab_name: str,
    key: str,
):
    """日本株・米国株共通の一覧とチャートを表示する。"""
    st.header(f"{tab_name}（スコア{SCORE_DISPLAY_THRESHOLD}以上）")

    if results_df.empty:
        st.info("該当する銘柄はありません。")
        return

    display_columns = [
        "銘柄コード",
        "銘柄名",
        "取引日",
        "終値",
        "前日比",
        "前日比率(%)",
        "RSI",
        "MACD",
        "Signal",
        "反発確度スコア",
        "判定",
    ]

    st.dataframe(
        results_df.reindex(columns=display_columns),
        use_container_width=True,
        hide_index=True,
    )

    st.subheader("🔥 反発確度スコア上位5")

    for _, row in results_df.head(5).iterrows():
        st.write(
            f"**{row['銘柄名']}（{row['銘柄コード']}）**  "
            f"スコア: **{row['反発確度スコア']}点**"
        )
        st.caption(
            f"取引日: {row['取引日']} / 終値: {row['終値']} / "
            f"前日比: {row['前日比']}（{row['前日比率(%)']}%）"
        )
        st.caption(row["判定"])

    selected_name = st.selectbox(
        "チャート表示銘柄を選択",
        results_df["銘柄名"].tolist(),
        key=f"select_{key}",
    )

    selected_ticker = results_df.loc[
        results_df["銘柄名"] == selected_name,
        "銘柄コード",
    ].iloc[0]

    selected_close = float(results_df.loc[
        results_df["銘柄コード"] == selected_ticker,
        "終値",
    ].iloc[0])

    chart_df = chart_data[selected_ticker]

    fig = plot_chart(
        df=chart_df,
        name=selected_name,
        ticker=selected_ticker,
    )
    st.pyplot(fig)
    plt.close(fig)

    show_analyst_price_targets(
        ticker=selected_ticker,
        name=selected_name,
        latest_close=selected_close,
    )


show_update_status()

st.divider()

with st.spinner("全銘柄を分析しています..."):
    results, chart_data = analyze_all_tickers()

if results:
    results_df = pd.DataFrame(results).sort_values(
        "反発確度スコア",
        ascending=False,
    )
    japan_df = results_df[
        results_df["銘柄コード"].str.endswith(".T")
    ].copy()
    us_df = results_df[
        ~results_df["銘柄コード"].str.endswith(".T")
    ].copy()
else:
    japan_df = pd.DataFrame()
    us_df = pd.DataFrame()

japan_tab, us_tab, backtest_tab, historical_backtest_tab, risk_backtest_tab = st.tabs(
    [
        f"🇯🇵 日本株（{len(japan_df)}銘柄）",
        f"🇺🇸 米国株（{len(us_df)}銘柄）",
        "📈 バックテスト",
        "🕰️ 過去データ検証",
        "⚖️ リスク検証",
    ]
)

with japan_tab:
    show_stock_tab(
        results_df=japan_df,
        chart_data=chart_data,
        tab_name="🇯🇵 日本株",
        key="japan",
    )

with us_tab:
    show_stock_tab(
        results_df=us_df,
        chart_data=chart_data,
        tab_name="🇺🇸 米国株",
        key="us",
    )

with backtest_tab:
    show_backtest_tab()

with historical_backtest_tab:
    show_historical_backtest_tab()

with risk_backtest_tab:
    show_risk_backtest_tab()
