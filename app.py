# app.py（高速版・200銘柄対応・終値更新状況は日本株/米株のみ）
import streamlit as st
import yfinance as yf
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib
import matplotlib.font_manager as fm
import json
from tickers import TICKERS

# =========================
# 日本語フォント設定（Streamlit Cloud用）
# =========================
font_path = "./fonts/ipaexg.ttf"
fm.fontManager.addfont(font_path)
matplotlib.rc('font', family='IPAexGothic')
matplotlib.rcParams['axes.unicode_minus'] = False

st.title("📊 寄り付き天底狙いスクリーナー（高速版：200銘柄＋スコア50以上）")

THRESHOLD = 1.0  # ±1%以内をタッチ判定

# =========================
# 📅 終値更新状況（GitHub Actions）
# =========================
st.header("📅 終値更新状況（GitHub Actions）")

try:
    with open("update_status.json", "r") as f:
        update_status = json.load(f)
except:
    update_status = {}

# 日本株代表：トヨタ（7203.T）
jp_ticker = "7203.T"
if jp_ticker in update_status:
    info = update_status[jp_ticker]
    if info["updated"]:
        st.success(f"日本株：終値更新済み（{info['last_update_time']}）")
    else:
        st.warning("日本株：終値未更新")
else:
    st.info("日本株：データなし")

# 米株代表：アップル（AAPL）
us_ticker = "AAPL"
if us_ticker in update_status:
    info = update_status[us_ticker]
    if info["updated"]:
        st.success(f"米株：終値更新済み（{info['last_update_time']}）")
    else:
        st.warning("米株：終値未更新")
else:
    st.info("米株：データなし")


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


# --- スコア計算 ---
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
def analyze_all():
    tickers_list = list(TICKERS.keys())

    # =========================
    # 🔥 200銘柄をまとめて高速取得
    # =========================
    df_all = yf.download(tickers_list, period="6mo", group_by="ticker")

    results = []
    chart_data = {}

    for ticker, name in TICKERS.items():
        try:
            df = df_all[ticker].dropna()
        except:
            continue

        if df.empty:
            continue

        df = df.ffill()

        # 終値・前日比
        latest_close = df["Close"].iloc[-1]
        previous_close = df["Close"].iloc[-2]
        diff = latest_close - previous_close
        pct = (diff / previous_close) * 100

        # テクニカル
        df["25MA"] = df["Close"].rolling(25).mean()
        df["High20"] = df["High"].rolling(20).max()
        df["Low20"] = df["Low"].rolling(20).min()

        latest_ma = df["25MA"].iloc[-1]
        latest_high20 = df["High20"].iloc[-1]
        latest_low20 = df["Low20"].iloc[-1]

        deviation_ma = ((latest_close - latest_ma) / latest_ma) * 100

        box_top_touch = abs(latest_close - latest_high20) <= (latest_high20 * THRESHOLD / 100)
        box_bottom_touch = abs(latest_close - latest_low20) <= (latest_low20 * THRESHOLD / 100)

        # RSI
        df["RSI"] = calc_rsi(df["Close"])
        latest_rsi = df["RSI"].iloc[-1]

        # MACD
        df["MACD"], df["Signal"] = calc_macd(df["Close"])
        latest_macd = df["MACD"].iloc[-1]
        latest_signal = df["Signal"].iloc[-1]

        # スコア
        score = calc_score(
            abs(deviation_ma) <= THRESHOLD,
            box_bottom_touch,
            latest_rsi,
            latest_macd,
            latest_signal
        )

        # 判定文字
        judges = []
        if abs(deviation_ma) <= THRESHOLD:
            judges.append("25MAタッチ（反発候補）")
        if box_top_touch:
            judges.append("ボックス上限タッチ（天井候補）")
        if box_bottom_touch:
            judges.append("ボックス下限タッチ（底候補）")

        judge = "・".join(judges) if judges else "判定なし"

        # スコア50以上のみ採用
        if score >= 50:
            results.append({
                "銘柄コード": ticker,
                "銘柄名": name,
                "判定": judge,
                "終値": round(latest_close, 1),
                "前日比": round(diff, 1),
                "前日比率(%)": round(pct, 2),
                "RSI": round(latest_rsi, 1),
                "MACD": round(latest_macd, 3),
                "Signal": round(latest_signal, 3),
                "反発確度スコア": score
            })

            chart_data[ticker] = df

    return results, chart_data


# --- 実行 ---
results, chart_data = analyze_all()

df_results = pd.DataFrame(results).sort_values("反発確度スコア", ascending=False)

# 日本株・米国株分離
df_jp = df_results[df_results["銘柄コード"].str.endswith(".T")]
df_us = df_results[~df_results["銘柄コード"].str.endswith(".T")]

# =========================
# 🇯🇵 日本株 / 🇺🇸 米国株 タブ表示
# =========================
tab_jp, tab_us = st.tabs(["🇯🇵 日本株（スコア50以上）", "🇺🇸 米国株（スコア50以上）"])

# -------------------------
# 🇯🇵 日本株
# -------------------------
with tab_jp:
    st.header("🇯🇵 日本株（スコア50以上）")
    st.dataframe(df_jp, use_container_width=True)

    st.header("🔥 日本株：反発確度スコア上位5")
    for idx, row in df_jp.head(5).iterrows():
        st.subheader(f"{row['銘柄名']}（{row['銘柄コード']}）")
        st.write(f"判定：**{row['判定']}**")
        st.write(f"スコア：**{row['反発確度スコア']}点**")
        st.write("---")

    # チャート
    if len(df_jp) > 0:
        st.header("📈 日本株チャート")
        selected_name = st.selectbox("銘柄を選択：", df_jp["銘柄名"])
        ticker = df_jp[df_jp["銘柄名"] == selected_name]["銘柄コード"].iloc[0]
        df_plot = chart_data[ticker]

        fig, ax = plt.subplots(figsize=(10, 5))
        ax.plot(df_plot.index, df_plot["Close"], label="終値")
        ax.plot(df_plot.index, df_plot["25MA"], label="25MA", linestyle="--")
        ax.plot(df_plot.index, df_plot["High20"], label="ボックス上限", linestyle=":")
        ax.plot(df_plot.index, df_plot["Low20"], label="ボックス下限", linestyle=":")
        ax.legend()
        ax.grid(True)
        st.pyplot(fig)

# -------------------------
# 🇺🇸 米国株
# -------------------------
with tab_us:
    st.header("🇺🇸 米国株（スコア50以上）")
    st.dataframe(df_us, use_container_width=True)

    st.header("🔥 米国株：反発確度スコア上位5")
    for idx, row in df_us.head(5).iterrows():
        st.subheader(f"{row['銘柄名']}（{row['銘柄コード']}）")
        st.write(f"判定：**{row['判定']}**")
        st.write(f"スコア：**{row['反発確度スコア']}点**")
        st.write("---")

    # チャート
    if len(df_us) > 0:
        st.header("📈 米国株チャート")
        selected_name = st.selectbox("銘柄を選択：", df_us["銘柄名"])
        ticker = df_us[df_us["銘柄名"] == selected_name]["銘柄コード"].iloc[0]
        df_plot = chart_data[ticker]

        fig, ax = plt.subplots(figsize=(10, 5))
        ax.plot(df_plot.index, df_plot["Close"], label="終値")
        ax.plot(df_plot.index, df_plot["25MA"], label="25MA", linestyle="--")
        ax.plot(df_plot.index, df_plot["High20"], label="ボックス上限", linestyle=":")
        ax.plot(df_plot.index, df_plot["Low20"], label="ボックス下限", linestyle=":")
        ax.legend()
        ax.grid(True)
        st.pyplot(fig)
