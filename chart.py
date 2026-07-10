# chart.py
import matplotlib.pyplot as plt

def plot_chart(df, name, ticker):
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(df.index, df['Close'], label="株価（終値）", color="blue")
    ax.plot(df.index, df['25MA'], label="25日移動平均線", color="orange", linestyle="--")
    ax.plot(df.index, df['High20'], label="ボックス上限（20日）", color="red", linestyle=":")
    ax.plot(df.index, df['Low20'], label="ボックス下限（20日）", color="green", linestyle=":")
    ax.set_title(f"{name} ({ticker}) - 過去6ヶ月")
    ax.legend()
    ax.grid(True)
    return fig
