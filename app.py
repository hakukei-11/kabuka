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

st.title("📊 寄り付き天底狙いスクリーナー（RSI＋MACD＋反発確度スコア）")

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

        df['25MA'] = df['Close'].rolling(25).mean()
        df['High20'] = df['High'].rolling(20).max()
        df['Low20'] = df['Low'].rolling(20).min()

        latest_close = df['Close'].iloc[-1]
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
            "RSI": round(latest_rsi, 1),
            "MACD": round(latest_macd, 3),
            "Signal": round(latest_signal, 3),
            "反発確度スコア": score
        })

        all_data[ticker] = df

    return results, all_data


# --- 実行 ---
results, all_stock_data = analyze_tickers()

st.header("🎯 寄り付き天底候補銘柄一覧（RSI＋MACD＋スコア付き）")
df_results = pd.DataFrame(results)
df_results = df_results.sort_values("反発確度スコア", ascending=False)
st.dataframe(df_results, use_container_width=True)

# --- おすすめ銘柄（スコア上位5） ---
st.header("🔥 反発確度スコア上位5銘柄（データ分析によるランキング）")

top5 = df_results.head(5)

for idx, row in top5.iterrows():
    st.subheader(f"{row['銘柄名']}（{row['銘柄コード']}）")
    st.write(f"判定：**{row['判定']}**")
    st.write(f"反発確度スコア：**{row['反発確度スコア']}点**")
    st.write(f"株価（終値）：{row['終値']}")
    st.write(f"RSI：{row['RSI']}")
    st.write(f"MACD：{row['MACD']} / Signal：{row['Signal']}")
    st.write("---")


# --- チャート表示 ---
st.header("📈 個別チャート表示")
selected_name = st.selectbox("銘柄を選択：", list(TICKERS.values()))
selected_ticker = [k for k, v in TICKERS.items() if v == selected_name][0]

df_plot = all_stock_data[selected_ticker]

fig, ax = plt.subplots(figsize=(10, 5))
ax.plot(df_plot.index, df_plot['Close'], label="株価（終値）", color="blue")
ax.plot(df_plot.index, df_plot['25MA'], label="25日移動平均線", color="orange", linestyle="--")
ax.plot(df_plot.index, df_plot['High20'], label="ボックス上限（20日）", color="red", linestyle=":")
ax.plot(df_plot.index, df_plot['Low20'], label="ボックス下限（20日）", color="green", linestyle=":")
ax.set_title(f"{selected_name} ({selected_ticker}) - 過去6ヶ月")
ax.legend()
ax.grid(True)

st.pyplot(fig)
