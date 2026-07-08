import streamlit as st
import yfinance as yf
import pandas as pd
import matplotlib.pyplot as plt

# 画面のタイトル設定
st.title("📊 日本株 + 米国株 25日移動平均線タッチ判定ツール")
st.write("日本株と米国株の中から、今日の株価が25日移動平均線に近づいている銘柄を判定します。")

# 日本株ティッカー
JP_TICKERS = {
    "7203.T": "トヨタ自動車",
    "6758.T": "ソニーグループ",
    "8306.T": "三菱UFJ FG",
    "7974.T": "任天堂",
    "9984.T": "ソフトバンクグループ",
    "6501.T": "日立製作所",
    "4502.T": "武田薬品工業"
}

# 米国株ティッカー
US_TICKERS = {
    "AAPL": "Apple",
    "MSFT": "Microsoft",
    "NVDA": "NVIDIA",
    "AMZN": "Amazon",
    "GOOGL": "Alphabet",
    "META": "Meta Platforms"
}

# タッチ判定の許容範囲（例: 1.0% 以内）
THRESHOLD = 1.0

# データ処理と判定の関数
@st.cache_data(ttl=3600)
def check_touch_tickers():
    touched_list = []
    all_data = {}

    # 日本株 + 米国株を統合
    ALL_TICKERS = {**JP_TICKERS, **US_TICKERS}

    for ticker, name in ALL_TICKERS.items():
        df = yf.Ticker(ticker).history(period="6m")
        if df.empty:
            continue

        df['25MA'] = df['Close'].rolling(window=25).mean()

        latest_close = df['Close'].iloc[-1]
        latest_ma = df['25MA'].iloc[-1]

        if pd.isna(latest_ma):
            continue

        deviation = ((latest_close - latest_ma) / latest_ma) * 100

        all_data[ticker] = df

        if abs(deviation) <= THRESHOLD:
            touched_list.append({
                "銘柄コード": ticker,
                "銘柄名": name,
                "最新終値": round(latest_close, 1),
                "25日移動平均": round(latest_ma, 1),
                "乖離率(%)": round(deviation, 2)
            })

    return touched_list, all_data

# 判定の実行
with st.spinner("最新の株価データを取得中..."):
    touched_tickers, all_stock_data = check_touch_tickers()

# --- 画面表示部分 ---

st.header("🎯 本日のタッチ銘柄（±1%以内）")
if touched_tickers:
    df_touched = pd.DataFrame(touched_tickers)
    st.dataframe(df_touched, use_container_width=True)
else:
    st.info("現在、25日移動平均線にタッチしている銘柄はありません。")

st.markdown("---")

st.header("📈 個別チャート確認")

# 日本株 + 米国株を統合して選択肢にする
ALL_TICKERS = {**JP_TICKERS, **US_TICKERS}

selected_name = st.selectbox("チャートを見たい銘柄を選んでください：", list(ALL_TICKERS.values()))
selected_ticker = [k for k, v in ALL_TICKERS.items() if v == selected_name][0]

if selected_ticker in all_stock_data:
    df_plot = all_stock_data[selected_ticker]

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(df_plot.index, df_plot['Close'], label="株価（終値）", color="blue")
    ax.plot(df_plot.index, df_plot['25MA'], label="25日移動平均線", color="orange", linestyle="--")
    ax.set_title(f"{selected_name} ({selected_ticker}) - 過去6ヶ月")
    ax.legend()
    ax.grid(True)

    st.pyplot(fig)
