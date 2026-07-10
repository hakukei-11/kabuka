# app.py
import streamlit as st
import yfinance as yf
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib
from tickers import TICKERS

# 日本語フォント設定
matplotlib.rcParams['font.family'] = 'MS Gothic'
matplotlib.rcParams['axes.unicode_minus'] = False

st.title("📊 寄り付き天底狙いスクリーナー（RSI＋MACD＋反発確度＋前日比）")

THRESHOLD = 1.0  # ±1%以内をタッチ判定


# --- RSI計算 ---
def calc_rsi(series, period=14):
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    ma_up = up.rolling(window=period).mean()
    ma_down = down.rolling(window=period).mean()
    rsi = 100 - (100 / (1 + (ma_up / ma_down)))
    return rsi


# --- MACD計算 ---
def calc_macd(series):
    ema12 = series.ewm(span=12, adjust=False).mean()
    ema26 = series.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    return macd, signal


# --- 反発確度スコア ---
def calc_score(is_25ma_touch, is_box_bottom_touch, rsi, macd, signal):
    score = 0

    if is_25ma_touch:
        score += 30

    if is_box_bottom_touch:
        score += 30

    if rsi <= 30:
        score += 20
    elif rsi <= 40:
        score += 10

    if macd > signal:
        score += 20

    return score


@st.cache_data(ttl=3600)
def analyze_tickers():
    results = []
    all_data = {}

    for ticker, name in TICKERS.items():
        df = yf.Ticker(ticker).history(period="6mo")

        if df is None or df.empty:
            continue

        df = df.ffill()

        # --- 当日終値と前日終値 ---
        latest_close = df['Close'].iloc[-1]
        previous_close = df['Close'].iloc[-2]
        diff = latest_close - previous_close
        pct = (diff / previous_close) * 100

        # --- テクニカル ---
        df['25MA'] = df['Close'].rolling(25).mean()
        df['High20'] = df['High'].rolling(20).max()
        df['Low20'] = df['Low'].rolling(20).min()

        latest_ma = df['25MA'].iloc[-1]
        latest_high20 = df['High20'].iloc[-1]
        latest_low20 = df['Low20'].iloc[-1]

        deviation_ma = ((latest_close - latest_ma) / latest_ma) * 100

        box_top_touch = abs(latest_close - latest_high20) <= (latest_high20 * THRESHOLD / 100)
        box_bottom_touch = abs(latest_close - latest_low20) <= (latest_low20 * THRESHOLD / 100)

        # RSI
        df['RSI'] = calc_rsi(df['Close'])
        latest_rsi = df['RSI'].iloc[-1]

        # MACD
        df['MACD'], df['Signal'] = calc_macd(df['Close'])
        latest_macd = df['MACD'].iloc[-1]
        latest_signal = df['Signal'].iloc[-1]

        # スコア
        score = calc_score(
            abs(deviation_ma) <= THRESHOLD,
            box_bottom_touch,
            latest_rsi,
            latest_macd,
            latest_signal
        )

        # 判定文字
        judge = ""
        if abs(deviation_ma) <= THRESHOLD:
            judge = "25MAタッチ（反発候補）"
        if box_top_touch:
            judge = "ボックス上限タッチ（天井候補）"
        if box_bottom_touch:
            judge = "ボックス下限タッチ（底候補）"

        results.append({
            "銘柄コード": ticker,
            "銘柄名": name,
            "判定": judge,
            "終値": round(latest_close, 1),
            "前日終値": round(previous_close, 1),
            "前日比": round(diff, 1),
            "前日比率(%)": round(pct, 2),
            "RSI": round(latest_rsi, 1),
            "MACD": round(latest_macd, 3),
            "Signal": round(latest_signal, 3),
            "反発確度スコア": score
        })

        all_data[ticker] = df

    return results, all_data


# --- 実行 ---
results, all_stock_data = analyze_tickers()

df_results = pd.DataFrame(results).sort_values("反発確度スコア", ascending=False)

# =========================
# 日本株・米国株を分離
# =========================
df_jp = df_results[df_results["銘柄コード"].str.endswith(".T")]
df_us = df_results[~df_results["銘柄コード"].str.endswith(".T")]

# =========================
# 🇯🇵 日本株 / 🇺🇸 米国株 タブ表示
# =========================
tab_jp, tab_us = st.tabs(["🇯🇵 日本株", "🇺🇸 米国株"])

# -------------------------
# 🇯🇵 日本株タブ
# -------------------------
with tab_jp:
    st.header("🇯🇵 日本株一覧（前日比＋RSI＋MACD＋スコア）")
    st.dataframe(df_jp, use_container_width=True)

    st.header("🔥 日本株：反発確度スコア上位5銘柄")
    top5_jp = df_jp.head(5)

    for idx, row in top5_jp.iterrows():
        st.subheader(f"{row['銘柄名']}（{row['銘柄コード']}）")
        st.write(f"判定：**{row['判定']}**")
        st.write(f"反発確度スコア：**{row['反発確度スコア']}点**")
        st.write(f"終値：{row['終値']}（前日比：{row['前日比']} / {row['前日比率(%)']}%）")
        st.write(f"RSI：{row['RSI']}")
        st.write(f"MACD：{row['MACD']} / Signal：{row['Signal']}")
        st.write("---")

    # チャート表示（日本株）
    st.header("📈 日本株チャート表示")
    selected_name_jp = st.selectbox("日本株を選択：", list(df_jp["銘柄名"]))
    selected_ticker_jp = df_jp[df_jp["銘柄名"] == selected_name_jp]["銘柄コード"].iloc[0]
    df_plot_jp = all_stock_data[selected_ticker_jp]

    fig_jp, ax_jp = plt.subplots(figsize=(10, 5))
    ax_jp.plot(df_plot_jp.index, df_plot_jp['Close'], label="株価（終値）", color="blue")
    ax_jp.plot(df_plot_jp.index, df_plot_jp['25MA'], label="25日移動平均線", color="orange", linestyle="--")
    ax_jp.plot(df_plot_jp.index, df_plot_jp['High20'], label="ボックス上限（20日）", color="red", linestyle=":")
    ax_jp.plot(df_plot_jp.index, df_plot_jp['Low20'], label="ボックス下限（20日）", color="green", linestyle=":")
    ax_jp.set_title(f"{selected_name_jp} ({selected_ticker_jp}) - 過去6ヶ月")
    ax_jp.legend()
    ax_jp.grid(True)
    st.pyplot(fig_jp)

# -------------------------
# 🇺🇸 米国株タブ
# -------------------------
with tab_us:
    st.header("🇺🇸 米国株一覧（前日比＋RSI＋MACD＋スコア）")
    st.dataframe(df_us, use_container_width=True)

    st.header("🔥 米国株：反発確度スコア上位5銘柄")
    top5_us = df_us.head(5)

    for idx, row in top5_us.iterrows():
        st.subheader(f"{row['銘柄名']}（{row['銘柄コード']}）")
        st.write(f"判定：**{row['判定']}**")
        st.write(f"反発確度スコア：**{row['反発確度スコア']}点**")
        st.write(f"終値：{row['終値']}（前日比：{row['前日比']} / {row['前日比率(%)']}%）")
        st.write(f"RSI：{row['RSI']}")
        st.write(f"MACD：{row['MACD']} / Signal：{row['Signal']}")
        st.write("---")

    # チャート表示（米国株）
    st.header("📈 米国株チャート表示")
    selected_name_us = st.selectbox("米国株を選択：", list(df_us["銘柄名"]))
    selected_ticker_us = df_us[df_us["銘柄名"] == selected_name_us]["銘柄コード"].iloc[0]
    df_plot_us = all_stock_data[selected_ticker_us]

    fig_us, ax_us = plt.subplots(figsize=(10, 5))
    ax_us.plot(df_plot_us.index, df_plot_us['Close'], label="株価（終値）", color="blue")
    ax_us.plot(df_plot_us.index, df_plot_us['25MA'], label="25日移動平均線", color="orange", linestyle="--")
    ax_us.plot(df_plot_us.index, df_plot_us['High20'], label="ボックス上限（20日）", color="red", linestyle=":")
    ax_us.plot(df_plot_us.index, df_plot_us['Low20'], label="ボックス下限（20日）", color="green", linestyle=":")
    ax_us.set_title(f"{selected_name_us} ({selected_ticker_us}) - 過去6ヶ月")
    ax_us.legend()
    ax_us.grid(True)
    st.pyplot(fig_us)
