# analysis.py

from analysis_engine import analyze_ticker


def analyze_tickers(tickers: dict[str, str]) -> tuple[list[dict], dict]:
    """
    指定された銘柄一覧を分析する。
    既存コードとの互換性を保つために残す共通窓口。
    """
    results = []
    all_data = {}

    for ticker, name in tickers.items():
        result, df = analyze_ticker(ticker, name)

        if result is None or df is None:
            continue

        results.append(result)
        all_data[ticker] = df

    return results, all_data