# app.py
import json

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

    chart_df = chart_data[selected_ticker]

    fig = plot_chart(
        df=chart_df,
        name=selected_name,
        ticker=selected_ticker,
    )
    st.pyplot(fig)
    plt.close(fig)


show_update_status()

st.divider()

with st.spinner("全銘柄を分析しています..."):
    results, chart_data = analyze_all_tickers()

if not results:
    st.warning("分析結果がありません。yfinanceの取得状況を確認してください。")
    st.stop()

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

japan_tab, us_tab = st.tabs(
    [
        f"🇯🇵 日本株（{len(japan_df)}銘柄）",
        f"🇺🇸 米国株（{len(us_df)}銘柄）",
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