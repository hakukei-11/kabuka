# app.py
import streamlit as st
import pandas as pd
import matplotlib
from tickers import TICKERS
from analysis import analyze_tickers
from chart import plot_chart

matplotlib.rcParams['font.family'] = 'MS Gothic'
matplotlib.rcParams['axes.unicode_minus'] = False

st.title("📊 寄り付き天底狙いスクリーナー（RSI＋MACD＋反発確度スコア）")

results, all_stock_data = analyze_tickers(TICKERS)

st.header("🎯 寄り付き天底候補銘柄一覧（RSI＋MACD＋スコア付き）")
df_results = pd.DataFrame(results).sort_values("反発確度スコア", ascending=False)
st.dataframe(df_results, use_container_width=True)

st.header("🔥 反発確度スコア上位5銘柄（データ分析によるランキング）")
top5 = df_results.head(5)
for _, row in top5.iterrows():
    st.subheader(f"{row['銘柄名']}（{row['銘柄コード']}）")
    st.write(f"判定：**{row['判定']}**")
    st.write(f"反発確度スコア：**{row['反発確度スコア']}点**")
    st.write(f"株価（終値）：{row['終値']}")
    st.write(f"RSI：{row['RSI']}")
    st.write(f"MACD：{row['MACD']} / Signal：{row['Signal']}")
    st.write("---")

st.header("📈 個別チャート表示")
selected_name = st.selectbox("銘柄を選択：", list(TICKERS.values()))
selected_ticker = [k for k, v in TICKERS.items() if v == selected_name][0]
fig = plot_chart(all_stock_data[selected_ticker], selected_name, selected_ticker)
st.pyplot(fig)
