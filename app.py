import streamlit as st
import yfinance as yf
import pandas as pd
import matplotlib.pyplot as plt

# 画面タイトル
st.title("📊 株価 25日移動平均線タッチ判定ツール")
st.write("日本株と米国株の中から、今日の株価が25日移動平均線に近づいている銘柄を判定します。")

# 判定対象銘柄
TICKERS = {
    "7203.T": "トヨタ自動車",
    "6758.T": "ソニーグループ",
    "8306.T": "三菱UFJ FG",
    "7974.T": "任天堂",
    "9984.T": "ソフトバンクグループ",
    "6501.T": "日立製作所",
    "4502.T": "武田薬品工業",
    "AAPL": "Apple",
    "MSFT": "Microsoft",
    "GOOGL": "Alphabet"
}

THRESHOLD = 1.0  # ±1%以内をタッチ判定

@st.cache_data(ttl=3600)
def check_touch_tickers():
    touched_list = []
    all_data = {}

    for ticker, name in TICKERS.items():
        df = yf.Ticker(ticker).history(period="6mo")

        if df is None or df.empty or 'Close' not in df.columns:
            continue

        # 欠損値補完（DataFrame全体を安全に前方補完）
        df = df.ffill()  # ← method引数なしでOK

        # Close列がDataFrameの場合はSeries化
        if isinstance(df['Close'], pd.DataFrame):
            df['Close'] = df['Close'].iloc[:, 0]

        # 25日移動平均線
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

# 判定実行
with st.spinner("最新の株価データを取得中..."):
    touched_tickers, all_stock_data = check_touch_tickers()

# 動作確認用出力
st.write("取得データ数:", len(all_stock_data))
st.write("タッチ銘柄数:", len(touched_tickers))

# 結果表示
st.header("🎯 本日のタッチ銘柄（±1%以内）")
if touched_tickers:
    df_touched = pd.DataFrame(touched_tickers)
    st.dataframe(df_touched, use_container_width=True)
else:
    st.info("現在、25日移動平均線にタッチしている銘柄はありません。")

st.markdown("---")

# 個別チャート確認
st.header("📈 個別チャート確認")
selected_name = st.selectbox("チャートを見たい銘柄を選んでください：", list(TICKERS.values()))
selected_ticker = [k for k, v in TICKERS.items() if v == selected_name][0]

if selected_ticker in all_stock_data:
    df_plot = all_stock_data[selected_ticker]

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(df_plot.index, df_plot['Close'], label="株価（終値）", color="blue")
    ax.plot(df_plot.index, df_plot['25MA'], label="25日移動平均線", color="orange", linestyle="--")
    ax.set_title(f"{selected_name} ({selected_ticker}) - 過去6ヶ月")
    ax.legend()
    ax.grid(True)

    st.pyplot(fig)
