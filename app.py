import streamlit as st
import yfinance as yf
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib 
from tickers import TICKERS   # ★ 銘柄テーブルを外部ファイルから読み込み

# ★ 日本語フォント設定（Windows向け）
matplotlib.rcParams['font.family'] = 'MS Gothic'      # または 'Yu Gothic'
matplotlib.rcParams['axes.unicode_minus'] = False     # マイナス記号の文字化け防止

# 画面タイトル
st.title("📊 寄り付き天底狙いスクリーナー")
st.write("25日移動平均線タッチとボックス圏タッチを検知し、翌日の寄り付きで天井・底を狙うための銘柄を抽出します。")

# 判定閾値（±1%以内をタッチと判定）
THRESHOLD = 1.0

@st.cache_data(ttl=3600)
def analyze_tickers():
    results = []
    all_data = {}

    for ticker, name in TICKERS.items():
        df = yf.Ticker(ticker).history(period="6mo")

        if df is None or df.empty or 'Close' not in df.columns:
            continue

        # 欠損値補完
        df = df.ffill()

        # CloseがDataFrameの場合はSeries化
        if isinstance(df['Close'], pd.DataFrame):
            df['Close'] = df['Close'].iloc[:, 0]

        # 25日移動平均線
        df['25MA'] = df['Close'].rolling(window=25).mean()

        # ボックス圏（過去20日間の高値・安値）
        df['High20'] = df['High'].rolling(20).max()
        df['Low20']  = df['Low'].rolling(20).min()

        latest_close = df['Close'].iloc[-1]
        latest_ma = df['25MA'].iloc[-1]
        latest_high20 = df['High20'].iloc[-1]
        latest_low20  = df['Low20'].iloc[-1]

        if pd.isna(latest_ma) or pd.isna(latest_high20) or pd.isna(latest_low20):
            continue

        # 乖離率（25MA）
        deviation_ma = ((latest_close - latest_ma) / latest_ma) * 100

        # ボックス圏タッチ判定
        box_top_touch = abs(latest_close - latest_high20) <= (latest_high20 * THRESHOLD / 100)
        box_bottom_touch = abs(latest_close - latest_low20) <= (latest_low20 * THRESHOLD / 100)

        # 結果保存
        all_data[ticker] = df

        # 25MAタッチ
        if abs(deviation_ma) <= THRESHOLD:
            results.append({
                "銘柄コード": ticker,
                "銘柄名": name,
                "判定": "25MAタッチ（反発候補）",
                "終値": round(latest_close, 1),
                "25MA": round(latest_ma, 1),
                "乖離率(%)": round(deviation_ma, 2)
            })

        # ボックス上限タッチ（天井候補）
        if box_top_touch:
            results.append({
                "銘柄コード": ticker,
                "銘柄名": name,
                "判定": "ボックス上限タッチ（天井候補）",
                "終値": round(latest_close, 1),
                "上限値": round(latest_high20, 1)
            })

        # ボックス下限タッチ（底候補）
        if box_bottom_touch:
            results.append({
                "銘柄コード": ticker,
                "銘柄名": name,
                "判定": "ボックス下限タッチ（底候補）",
                "終値": round(latest_close, 1),
                "下限値": round(latest_low20, 1)
            })

    return results, all_data


# 判定実行
with st.spinner("最新の株価データを取得中..."):
    results, all_stock_data = analyze_tickers()

# 動作確認用出力
st.write("取得データ数:", len(all_stock_data))
st.write("検知銘柄数:", len(results))

# 結果表示
st.header("🎯 寄り付き天底候補銘柄一覧")
if results:
    df_results = pd.DataFrame(results)
    st.dataframe(df_results, use_container_width=True)
else:
    st.info("現在、天井・底候補の銘柄はありません。")

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
    ax.plot(df_plot.index, df_plot['High20'], label="ボックス上限（20日）", color="red", linestyle=":")
    ax.plot(df_plot.index, df_plot['Low20'], label="ボックス下限（20日）", color="green", linestyle=":")
    ax.set_title(f"{selected_name} ({selected_ticker}) - 過去6ヶ月")
    ax.legend()
    ax.grid(True)

    st.pyplot(fig)
